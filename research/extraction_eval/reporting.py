"""Reporting (§22): CSV / Markdown / LaTeX tables + figures, all derived from result
files. No metric is ever hand-typed — every number here comes from scored records.
"""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from pathlib import Path

from .scoring import CaseScore, aggregate

# Error family grouping for the error-analysis table (§19).
ERROR_FAMILIES = {
    "structured_output_error": "invalid_structured_output",
    "schema_validation_error": "invalid_structured_output",
    "refusal": "refusal",
    "truncation": "truncation",
    "empty_response": "empty_response",
    "rate_limit_error": "provider_failure",
    "provider_error": "provider_failure",
    "network_error": "provider_failure",
    "unknown_error": "provider_failure",
}


def _fmt(x: float | None) -> str:
    return "" if x is None else f"{x:.4f}"


def provider_summary_rows(scores_by_provider: dict[str, list[CaseScore]]) -> list[dict]:
    rows = []
    for provider in sorted(scores_by_provider):
        agg = aggregate(scores_by_provider[provider])
        rows.append({
            "provider": provider,
            "n_cases": agg.n_cases,
            "n_scored": agg.n_scored,
            "n_errors": agg.n_errors,
            "precision": _fmt(agg.precision),
            "recall": _fmt(agg.recall),
            "f1": _fmt(agg.f1),
            "exact_match_rate": _fmt(agg.exact_match_rate),
            "false_memory_rate": _fmt(agg.false_memory_rate),
            "missed_memory_rate": _fmt(agg.missed_memory_rate),
            "noop_accuracy": _fmt(agg.noop_accuracy),
            "type_accuracy": _fmt(agg.type_accuracy),
            "policy_accuracy": _fmt(agg.policy_accuracy),
        })
    return rows


def category_summary_rows(scores: list[CaseScore]) -> list[dict]:
    by: dict[tuple[str, str], list[CaseScore]] = defaultdict(list)
    for s in scores:
        by[(s.provider, s.category)].append(s)
    rows = []
    for (provider, category) in sorted(by):
        agg = aggregate(by[(provider, category)])
        rows.append({
            "provider": provider, "category": category,
            "n_scored": agg.n_scored, "f1": _fmt(agg.f1),
            "precision": _fmt(agg.precision), "recall": _fmt(agg.recall),
            "noop_accuracy": _fmt(agg.noop_accuracy),
        })
    return rows


def error_analysis_rows(scores: list[CaseScore]) -> list[dict]:
    fam = Counter()
    cls = Counter()
    for s in scores:
        if not s.scored and s.error_class:
            cls[s.error_class] += 1
            fam[ERROR_FAMILIES.get(s.error_class, "provider_failure")] += 1
    rows = [{"error_family": f, "error_class": "", "count": n} for f, n in sorted(fam.items())]
    rows += [{"error_family": ERROR_FAMILIES.get(c, "provider_failure"), "error_class": c, "count": n}
             for c, n in sorted(cls.items())]
    return rows


def to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def to_markdown(rows: list[dict]) -> str:
    if not rows:
        return "_(no rows)_\n"
    cols = list(rows[0].keys())
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out) + "\n"


def to_latex(rows: list[dict]) -> str:
    if not rows:
        return "% no rows\n"
    cols = list(rows[0].keys())
    lines = ["\\begin{tabular}{" + "l" * len(cols) + "}", "\\hline",
             " & ".join(c.replace("_", r"\_") for c in cols) + " \\\\", "\\hline"]
    for r in rows:
        lines.append(" & ".join(str(r[c]).replace("_", r"\_") for c in cols) + " \\\\")
    lines += ["\\hline", "\\end{tabular}"]
    return "\n".join(lines) + "\n"


def write_tables(scores_by_provider: dict[str, list[CaseScore]], out_dir: str | Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    all_scores = [s for v in scores_by_provider.values() for s in v]
    written = []
    for name, rows in (
        ("provider_summary", provider_summary_rows(scores_by_provider)),
        ("category_summary", category_summary_rows(all_scores)),
        ("error_analysis", error_analysis_rows(all_scores)),
    ):
        (out_dir / f"{name}.csv").write_text(to_csv(rows))
        (out_dir / f"{name}.md").write_text(to_markdown(rows))
        (out_dir / f"{name}.tex").write_text(to_latex(rows))
        written += [out_dir / f"{name}.csv", out_dir / f"{name}.md", out_dir / f"{name}.tex"]
    return written


def write_figures(scores_by_provider: dict[str, list[CaseScore]], out_dir: str | Path) -> list[Path]:
    """Publication figures. Returns [] (with a .skipped marker) if matplotlib is absent —
    tables still fully describe the results."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        (out_dir / "FIGURES.skipped").write_text("matplotlib not installed; tables carry all numbers\n")
        return []

    providers = sorted(scores_by_provider)
    aggs = {p: aggregate(scores_by_provider[p]) for p in providers}
    metrics = [("precision", lambda a: a.precision), ("recall", lambda a: a.recall),
               ("f1", lambda a: a.f1), ("exact", lambda a: a.exact_match_rate)]
    fig, ax = plt.subplots(figsize=(7, 4))
    x = range(len(providers))
    width = 0.2
    for i, (label, fn) in enumerate(metrics):
        vals = [(fn(aggs[p]) or 0.0) for p in providers]
        ax.bar([xi + i * width for xi in x], vals, width, label=label)
    ax.set_xticks([xi + 1.5 * width for xi in x])
    ax.set_xticklabels(providers)
    ax.set_ylim(0, 1)
    ax.set_ylabel("score")
    ax.set_title("Extraction quality by provider")
    ax.legend()
    fig.tight_layout()
    path = out_dir / "fig1_extraction_quality.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return [path]
