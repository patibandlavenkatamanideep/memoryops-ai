"""SQL profiling must count statements without ever capturing their data.

The profiler exists to answer a counting question, so the counting has to be right;
but it runs against a real database holding real tenant data, so the safety property
matters more. Both are pinned here. No database is required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlprofile import MAX_SHAPE_CHARS, SqlProfile, normalize  # noqa: E402


# ── normalization removes data, not structure ────────────────────────────────
def test_string_literals_are_stripped():
    out = normalize("SELECT * FROM memory_records WHERE tenant_id = 'acme_corp'")
    assert "acme_corp" not in out
    assert "SELECT" in out and "memory_records" in out


def test_tenant_and_user_values_cannot_survive():
    sql = "SELECT id FROM memory_records WHERE tenant_id = 'acme' AND user_id = 'alice'"
    out = normalize(sql)
    assert "acme" not in out and "alice" not in out


def test_memory_content_cannot_survive():
    sql = "INSERT INTO memory_records (content) VALUES ('my badge number is 7788')"
    out = normalize(sql)
    assert "badge" not in out and "7788" not in out


def test_a_credential_shaped_literal_cannot_survive():
    secret = "sk" + "-" + "live" + "0123456789abcdef"
    out = normalize(f"INSERT INTO memory_records (content) VALUES ('{secret}')")
    assert secret not in out


def test_embedding_vectors_collapse_to_a_single_token():
    """A 1536-element literal must not become 1536 separate placeholders."""
    vector = "[" + ",".join(f"{i / 1000:.6f}" for i in range(1536)) + "]"
    out = normalize(f"SELECT id FROM memory_records ORDER BY embedding <=> '{vector}'")
    assert "0.001" not in out
    assert out.count("?") <= 2
    assert len(out) <= MAX_SHAPE_CHARS


def test_numbers_and_placeholders_are_stripped():
    out = normalize("SELECT * FROM t WHERE a = 42 AND b = 3.5 AND c = $1 AND d = %(x)s")
    assert "42" not in out and "3.5" not in out


def test_shape_is_truncated():
    assert len(normalize("SELECT " + ", ".join(f"col_{i}" for i in range(500)))) <= MAX_SHAPE_CHARS


def test_normalization_is_stable_across_differing_values():
    """Grouping only works if two equivalent statements normalize identically."""
    a = normalize("SELECT id FROM memory_records WHERE tenant_id = 'acme'")
    b = normalize("SELECT id FROM memory_records WHERE tenant_id = 'globex'")
    assert a == b


def test_different_statements_do_not_collapse_together():
    a = normalize("SELECT id FROM memory_records WHERE tenant_id = 'acme'")
    b = normalize("SELECT id FROM loop_events WHERE tenant_id = 'acme'")
    assert a != b


def test_empty_statement_is_handled():
    assert normalize("") == ""


# ── counting and grouping ────────────────────────────────────────────────────
def test_statements_are_counted_and_grouped():
    p = SqlProfile()
    for tenant in ("acme", "globex", "initech"):
        p.record(f"SELECT id FROM memory_records WHERE tenant_id = '{tenant}'", 1.0)
    p.record("select set_config('app.tenant_id', 'acme', true)", 0.5)
    assert p.statements == 4
    assert len(p.by_shape) == 2, "equivalent statements must group into one shape"
    assert max(p.by_shape.values()) == 3


def test_per_shape_timing_accumulates():
    p = SqlProfile()
    p.record("SELECT 1 FROM t WHERE a = 'x'", 10.0)
    p.record("SELECT 1 FROM t WHERE a = 'y'", 5.0)
    assert p.total_ms == pytest.approx(15.0)
    assert p.top_shapes()[0]["total_ms"] == pytest.approx(15.0)
    assert p.top_shapes()[0]["count"] == 2


def test_top_shapes_are_ordered_by_frequency():
    p = SqlProfile()
    for _ in range(5):
        p.record("select set_config('a', 'b', true)", 0.1)
    p.record("SELECT id FROM memory_records WHERE tenant_id = 'acme'", 50.0)
    assert p.top_shapes()[0]["count"] == 5


def test_reset_clears_everything():
    p = SqlProfile()
    p.record("SELECT 1", 1.0)
    p.reset()
    assert p.statements == 0 and p.total_ms == 0.0 and not p.by_shape


# ── serialization ────────────────────────────────────────────────────────────
def test_summary_reports_per_request_figures():
    p = SqlProfile()
    for _ in range(234):
        p.record("SELECT id FROM memory_records WHERE tenant_id = 'acme'", 0.5)
    out = p.as_dict(requests=2)
    assert out["statements_total"] == 234
    assert out["statements_per_request"] == 117.0
    assert out["db_execution_ms_per_request"] == pytest.approx(58.5)


def test_serialized_summary_contains_no_parameter_values():
    p = SqlProfile()
    secret = "sk" + "-" + "live" + "0123456789abcdef"
    p.record(f"SELECT id FROM memory_records WHERE tenant_id = 'acme' AND k = '{secret}'", 1.0)
    blob = repr(p.as_dict(requests=1))
    assert secret not in blob and "acme" not in blob


def test_summary_survives_zero_requests():
    assert SqlProfile().as_dict(requests=0)["statements_per_request"] == 0.0
