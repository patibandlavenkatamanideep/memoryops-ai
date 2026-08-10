"""Recorded real-provider Gemini extraction evidence.

`benchmark/EXTRACTION_QUALITY.md` reports a real `gemini-2.5-flash` run scoring
0.94 / 0.94 / 0.94 on a fixed 25-turn dataset. That number came from a live call
sequence, so nothing in CI could reproduce or contradict it — the strongest capability
claim in the repository rested on a run nobody else could repeat.

This module turns that into evidence. One live recording was captured through the
*same* path the evaluator uses (`build_llm_provider` -> `extract_memories` ->
`GeminiProvider` -> `google-genai`), sanitized, and committed as a VCR cassette. CI
replays it with no credential and no network.

What the cassette proves and does not prove
-------------------------------------------
It proves a previously recorded real `gemini-2.5-flash` run regenerates the reported
score deterministically. It does **not** predict what a live Gemini call will score
tomorrow: models change server-side, and a cassette is a record, not a forecast.

Why extraction *mode* is asserted, not just request count
---------------------------------------------------------
`extract_memories` falls back to the deterministic heuristic whenever a provider call
fails (invariant #4). A headline "real provider" score can therefore be part stub
while still issuing 25 HTTP requests. The runtime already reports
`ExtractionOutcome.mode`, so every turn is asserted `structured` — 25 requests is not
evidence of 25 structured extractions.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_REPO_ROOT = _TESTS.parents[2]
_CASSETTE_DIR = _TESTS / "cassettes"
_CASSETTE = _CASSETTE_DIR / "test_extraction_quality_real_gemini.yaml"

#: The recorded run's identity. Asserted rather than assumed so a model-default change
#: cannot silently repoint the evidence at a different model.
RECORDED_MODEL = "gemini-2.5-flash"
EXPECTED_INTERACTIONS = 25

#: Replay needs a non-empty key only because provider construction requires one; no
#: credential is involved. Deliberately not shaped like a Google API key.
REPLAY_PLACEHOLDER_KEY = "recorded-replay-placeholder"


def _sdk_installed() -> bool:
    """`find_spec` raises when the parent package is absent, so guard it."""
    try:
        return importlib.util.find_spec("google.genai") is not None
    except ModuleNotFoundError:
        return False


_HAS_SDK = _sdk_installed()


# ── VCR configuration ────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def vcr_cassette_dir() -> str:
    """Flat `tests/cassettes/`, overriding pytest-recording's per-module default.

    The default is `cassettes/<module>/<test>.yaml`; the repository's existing
    convention (and `cassettes/README.md`) is the flat form.
    """
    return str(_CASSETTE_DIR)


@pytest.fixture(scope="module")
def vcr_config() -> dict:
    """Credential scrubbing and request matching.

    Filters cover every credential surface `google-genai` actually uses —
    `x-goog-api-key` for API-key auth and `Authorization` on its token paths — plus
    the `key` query parameter defensively, since a query-string credential is
    supported by the Gemini REST API even though this SDK version sends a header.
    Values are **removed**, not masked: a partially masked key is still a leak.

    Matching includes the request body because all 25 interactions hit the same
    endpoint. Without it, replay would pair responses by ordering alone, and a
    reordered or partially-run suite would silently score against the wrong
    prompt/response pairs. Credential-bearing headers are deliberately not matched on.
    """
    return {
        "filter_headers": [
            ("x-goog-api-key", None),
            ("authorization", None),
            ("x-api-key", None),
            ("api-key", None),
            ("x-goog-api-client", None),
        ],
        "filter_query_parameters": [("key", None)],
        "match_on": ["method", "scheme", "host", "port", "path", "query", "body"],
        "decode_compressed_response": True,
    }


@pytest.fixture
def _gemini_env(monkeypatch):
    """Provide a key only if the environment has none (i.e. during replay)."""
    monkeypatch.setenv("MEMORYOPS_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_MODEL", RECORDED_MODEL)
    if not os.getenv("GEMINI_API_KEY"):
        monkeypatch.setenv("GEMINI_API_KEY", REPLAY_PLACEHOLDER_KEY)
    # google-genai also reads GOOGLE_API_KEY; keep it out of the way so the recorded
    # identity cannot come from a second, unnoticed source.
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def _scorer():
    """Reuse the evaluator rather than duplicating its scoring."""
    evals_dir = str(_REPO_ROOT / "evals")
    if evals_dir not in sys.path:
        sys.path.insert(0, evals_dir)
    import run_extraction_quality as req

    return req


# ── the evidence test ────────────────────────────────────────────────────────
@pytest.mark.vcr
@pytest.mark.skipif(not _HAS_SDK, reason="google-genai not installed (optional extra)")
def test_extraction_quality_real_gemini(_gemini_env):
    """Replay the recorded run and regenerate the published score.

    Skips only where the optional SDK is absent (the default `requirements-dev.txt`
    suite). The dedicated CI evidence step installs the extra, so a skip *there* is a
    CI failure — see `.github/workflows/ci.yml`.
    """
    req = _scorer()
    cases = req._load_cases()
    assert len(cases) == EXPECTED_INTERACTIONS, f"dataset drifted: {len(cases)} turns"

    score = req.score_provider("gemini", cases)

    # No turn may have been rescued by the heuristic, and none may have errored.
    assert score.errors == [], score.errors
    assert score.modes == {"structured": EXPECTED_INTERACTIONS}, (
        f"expected {EXPECTED_INTERACTIONS} structured extractions, got {score.modes} — "
        "a fallback means part of this score is not real-provider evidence"
    )

    # Raw counts first. Two-decimal metrics can survive a scoring-logic change by
    # coincidence — 30/31 and 60/62 both render as 0.97 — so the counts are what
    # actually pin the recorded behaviour.
    assert (score.tp, score.extracted) == (30, 31), "precision inputs changed"
    assert (score.covered, score.expected) == (32, 34), "recall inputs changed"

    # The published row in benchmark/EXTRACTION_QUALITY.md, to two decimals.
    assert f"{score.precision:.2f}" == "0.97"
    assert f"{score.recall:.2f}" == "0.94"
    assert f"{score.f1:.2f}" == "0.95"
    assert (score.noop_ok, score.noop_total) == (3, 3)
    assert (score.multi_ok, score.multi_total) == (7, 9)


# ── cassette integrity and sanitization (no SDK required) ────────────────────
# These run in the base `requirements-dev.txt` suite, where the provider replay
# skips. The committed artifact is checked even where it cannot be replayed.

def _cassette_text() -> str:
    return _CASSETTE.read_text(encoding="utf-8", errors="replace")


def test_cassette_is_committed():
    assert _CASSETTE.exists(), (
        f"{_CASSETTE.name} is missing — the recorded Gemini evidence is the point of "
        "this module; record it per cassettes/README.md"
    )


def test_cassette_has_the_expected_interaction_count():
    """One request per dataset turn; more would mean retries were recorded.

    An earlier attempt produced 75 interactions — 25 turns retried three times
    against a provider that was rejecting every request. Counting them is how that
    is caught without reading the responses.
    """
    body = _cassette_text()
    assert body.count("\n- request:") == EXPECTED_INTERACTIONS, (
        f"expected {EXPECTED_INTERACTIONS} interactions in {_CASSETTE.name}"
    )


def test_cassette_contains_only_successful_responses():
    """Every recorded response must be a 200.

    The first recording attempt captured 25 x HTTP 400 and still produced a
    scoreable cassette, because the heuristic fallback answered every turn. A
    cassette of error responses is not provider evidence.
    """
    import yaml

    interactions = yaml.safe_load(_cassette_text())["interactions"]
    codes = {i["response"]["status"]["code"] for i in interactions}
    assert codes == {200}, f"non-200 responses recorded: {sorted(codes)}"


def test_cassette_records_the_expected_model():
    assert RECORDED_MODEL in _cassette_text()


# Patterns assembled from parts so this file contains no credential-shaped literal —
# the same reason `_secret_fixtures.py` exists. A scanner cannot tell a detection
# fixture from a live key.
_GOOGLE_KEY_RE = re.compile("AI" + "za" + r"[0-9A-Za-z_\-]{35}")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}")


@pytest.mark.parametrize(
    ("label", "pattern"),
    [
        ("google api key", _GOOGLE_KEY_RE),
        ("bearer credential", _BEARER_RE),
    ],
)
def test_cassette_contains_no_credential_material(label, pattern):
    """Fails naming only the credential *category*, never the value."""
    if not _CASSETTE.exists():
        pytest.skip("cassette not recorded yet")
    assert not pattern.search(_cassette_text()), (
        f"{_CASSETTE.name} contains {label} material; re-record with the filters in "
        "vcr_config and do not commit the current file"
    )


@pytest.mark.parametrize("header", ["x-goog-api-key", "authorization", "x-api-key", "api-key"])
def test_cassette_has_no_unsanitized_credential_headers(header):
    if not _CASSETTE.exists():
        pytest.skip("cassette not recorded yet")
    for line in _cassette_text().splitlines():
        stripped = line.strip().lower()
        if stripped.startswith(f"{header}:") or stripped.startswith(f"- {header}:"):
            value = stripped.split(":", 1)[1].strip()
            assert value in ("", "null", "[]", "none"), (
                f"{_CASSETTE.name} carries an unsanitized '{header}' header"
            )


def test_cassette_has_no_key_query_parameter():
    if not _CASSETTE.exists():
        pytest.skip("cassette not recorded yet")
    assert not re.search(r"[?&]key=[^&\s\"']+", _cassette_text()), (
        f"{_CASSETTE.name} carries a 'key' query-string credential"
    )


def test_cassette_does_not_contain_the_local_gemini_key():
    """The strongest available check: compare against the real key, if one exists.

    Never prints or logs the value — only whether it appears.
    """
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key == REPLAY_PLACEHOLDER_KEY:
        pytest.skip("no real GEMINI_API_KEY in this environment to compare against")
    if not _CASSETTE.exists():
        pytest.skip("cassette not recorded yet")
    assert key not in _cassette_text(), (
        f"{_CASSETTE.name} contains the live GEMINI_API_KEY — delete it, do not commit"
    )


def test_replay_placeholder_is_not_credential_shaped():
    """The placeholder must never be mistaken for, or become, a real credential."""
    assert not _GOOGLE_KEY_RE.match(REPLAY_PLACEHOLDER_KEY)
    assert "AI" + "za" not in REPLAY_PLACEHOLDER_KEY
    assert len(REPLAY_PLACEHOLDER_KEY) < 39
