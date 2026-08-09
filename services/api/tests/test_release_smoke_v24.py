"""The release smoke harness's own failure modes.

The harness asserts a production security boundary, so the ways it can be *wrong*
matter as much as the checks it makes. Two were found during the v2.4 release and
are pinned here:

* a missing CA bundle produced twelve "failed" checks that read as a breached trust
  boundary, while ``curl`` reached the same URLs successfully;
* the worker heartbeat check asserted only ``status == 200``, so a deployment whose
  worker health was not observable at all (``{"healthy": false}``) passed it.

These are unit tests over the classification logic — they make no network calls and
need no deployment.
"""

from __future__ import annotations

import ssl
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import release_smoke_v24 as smoke  # noqa: E402


# ── TLS/CA failures are environment faults, not boundary results ────────────
def test_a_certificate_failure_is_classified_as_its_own_status(monkeypatch):
    """`CERTIFICATE_VERIFY_FAILED` must not look like an HTTP answer."""

    def raise_cert_error(*args, **kwargs):
        raise urllib.error.URLError(
            ssl.SSLCertVerificationError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate"
            )
        )

    monkeypatch.setattr(smoke.urllib.request, "urlopen", raise_cert_error)
    status, body, _ = smoke.request("GET", "https://example.test/healthz")

    assert status == smoke.STATUS_TLS_ERROR
    assert status != smoke.STATUS_CONNECTION_ERROR
    assert "TLS certificate verification failed" in body


def test_a_certificate_failure_is_never_reported_as_a_denied_check():
    """The specific misreading to prevent.

    A TLS fault must not satisfy a DENIED expectation, or a machine with no CA
    bundle would "prove" that every protected route was correctly refusing callers.
    """
    ok, detail = smoke._classify(smoke.STATUS_TLS_ERROR, smoke.DENIED)
    assert ok is False
    assert "environment fault" in detail

    ok, detail = smoke._classify(smoke.STATUS_TLS_ERROR, smoke.ALLOWED)
    assert ok is False
    assert "environment fault" in detail


def test_an_ordinary_connection_error_stays_distinct_from_a_tls_error(monkeypatch):
    def raise_conn_error(*args, **kwargs):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(smoke.urllib.request, "urlopen", raise_conn_error)
    status, body, _ = smoke.request("GET", "https://example.test/healthz")

    assert status == smoke.STATUS_CONNECTION_ERROR
    assert "connection error" in body


def test_the_preflight_reports_a_certificate_failure(monkeypatch):
    monkeypatch.setattr(
        smoke, "request", lambda *a, **k: (smoke.STATUS_TLS_ERROR, "cert bad", {})
    )
    assert smoke.tls_preflight("https://example.test") == "cert bad"


def test_the_preflight_is_silent_when_tls_works(monkeypatch):
    monkeypatch.setattr(smoke, "request", lambda *a, **k: (200, {"status": "ok"}, {}))
    assert smoke.tls_preflight("https://example.test") is None


def test_the_environment_exit_code_is_distinct_from_failure_and_incomplete():
    """CI must be able to tell "boundary is wrong" from "this machine cannot do TLS"."""
    codes = {
        smoke.EXIT_PASS,
        smoke.EXIT_FAIL,
        smoke.EXIT_INCOMPLETE,
        smoke.EXIT_ENVIRONMENT,
    }
    assert len(codes) == 4
    assert smoke.EXIT_ENVIRONMENT not in (smoke.EXIT_FAIL, smoke.EXIT_INCOMPLETE)


# ── C1 worker heartbeat requires healthy is exactly True ────────────────────
def _worker_health_result(body, status: int = 200) -> smoke.Results:
    r = smoke.Results()
    responses = {
        "/healthz": (200, {"status": "ok"}, {}),
        "/readyz": (200, {"ready": True}, {}),
        "/healthz/workers": (status, body, {}),
    }

    def fake_request(method, url, **kwargs):
        for suffix, response in responses.items():
            if url.endswith(suffix):
                return response
        raise AssertionError(f"unexpected url {url}")

    original = smoke.request
    smoke.request = fake_request
    try:
        smoke.section_infrastructure("https://example.test", r)
    finally:
        smoke.request = original
    return r


def _worker_check(r: smoke.Results) -> tuple[bool, str]:
    for name in r.passed:
        if "worker heartbeat" in name:
            return True, name
    for name, detail in r.failed:
        if "worker heartbeat" in name:
            return False, detail
    raise AssertionError("worker heartbeat check did not run")


def test_worker_heartbeat_passes_only_on_healthy_true():
    ok, _ = _worker_check(_worker_health_result({"healthy": True}))
    assert ok


@pytest.mark.parametrize(
    "body",
    [
        {"healthy": False},
        {"healthy": None},
        {},
        {"status": "ok"},
        "not json at all",
    ],
    ids=["false", "null", "missing", "wrong-key", "non-json"],
)
def test_worker_heartbeat_fails_on_anything_but_true(body):
    """A 200 alone is not evidence of a healthy worker.

    `{"healthy": false}` is exactly what a deployment without
    OPERATIONAL_DATABASE_URL returns — worker health is not observable, which is
    not the same as a worker being fine.
    """
    ok, detail = _worker_check(_worker_health_result(body))
    assert not ok
    assert "OPERATIONAL_DATABASE_URL" in detail


def test_worker_heartbeat_fails_on_non_200_even_when_body_says_healthy():
    ok, _ = _worker_check(_worker_health_result({"healthy": True}, status=503))
    assert not ok


# ── the harness never weakens TLS ───────────────────────────────────────────
def test_the_harness_contains_no_verification_bypass():
    """A green run must never have been bought by disabling certificate checks."""
    source = (REPO_ROOT / "scripts" / "release_smoke_v24.py").read_text(encoding="utf-8")
    for bypass in (
        "_create_unverified_context",
        "CERT_NONE",
        "check_hostname = False",
        "verify=False",
    ):
        assert bypass not in source, f"TLS verification bypass present: {bypass}"
