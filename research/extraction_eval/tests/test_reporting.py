"""Reporting tests — tables derive from scores; figures render or skip cleanly."""

from __future__ import annotations

import pytest

from research.extraction_eval.reporting import (
    error_analysis_rows,
    provider_summary_rows,
    to_csv,
    to_latex,
    to_markdown,
    write_figures,
    write_tables,
)
from research.extraction_eval.scoring import CaseScore


def _scores():
    return {
        "stub": [CaseScore("c1", "single_memory", "stub", 1, tp=1),
                 CaseScore("c2", "no_persistent_memory", "stub", 1, expected_noop=True, noop_correct=True)],
        "gemini": [CaseScore("c1", "single_memory", "gemini", 1, tp=1, fp=1),
                   CaseScore("c2", "no_persistent_memory", "gemini", 1, scored=False, error_class="refusal")],
    }


def test_provider_summary_derives_from_scores():
    rows = provider_summary_rows(_scores())
    assert {r["provider"] for r in rows} == {"stub", "gemini"}
    # gemini has one error -> reported, not silently dropped.
    g = next(r for r in rows if r["provider"] == "gemini")
    assert g["n_errors"] == 1


def test_error_analysis_reports_families():
    rows = error_analysis_rows([s for v in _scores().values() for s in v])
    assert any(r["error_class"] == "refusal" for r in rows)


def test_table_formats_render():
    rows = provider_summary_rows(_scores())
    assert "provider" in to_csv(rows)
    assert "| provider" in to_markdown(rows)
    assert "tabular" in to_latex(rows)


def test_write_tables_produces_files(tmp_path):
    written = write_tables(_scores(), tmp_path)
    assert (tmp_path / "provider_summary.csv").exists()
    assert len(written) == 9  # 3 tables x (csv/md/tex)


def test_figures_render_or_skip(tmp_path):
    pytest.importorskip  # noqa: B018 — presence check only
    figs = write_figures(_scores(), tmp_path)
    try:
        import matplotlib  # noqa: F401

        assert figs and figs[0].exists()
    except Exception:  # noqa: BLE001
        assert (tmp_path / "FIGURES.skipped").exists()
