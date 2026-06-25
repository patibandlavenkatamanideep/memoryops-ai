"""Per-request economics estimation (advisory).

Pure functions over deterministic token estimates (reusing
`compression.metrics.estimate_tokens`) and the advisory price table. Nothing here
does I/O or can block a request; the gateway calls it inside a no-throw guard.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..compression.metrics import estimate_tokens
from .pricing import price_per_1m


def estimate_cost_usd(model: str, tokens: int, *, kind: str, overrides_json: str = "") -> float:
    """Estimated USD cost of ``tokens`` for ``model``. 0.0 when unpriced.

    ``kind`` selects which price applies: "embedding" | "input" | "output".
    """
    price = price_per_1m(model, overrides_json=overrides_json)
    if price is None or tokens <= 0:
        return 0.0
    rate = {"embedding": price.embedding, "input": price.input, "output": price.output}.get(
        kind, 0.0
    )
    return round(tokens / 1_000_000 * rate, 8)


@dataclass(frozen=True)
class RequestEconomics:
    """Advisory token + cost rollup for a single chat request."""

    embedding_model: str = ""
    llm_model: str = ""
    embedding_tokens: int = 0
    context_tokens: int = 0
    compressed_tokens: int = 0
    tokens_saved: int = 0
    llm_input_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cost_saved_usd: float = 0.0
    priced: bool = False  # True when at least one model resolved to a price

    def as_dict(self) -> dict:
        return asdict(self)


def build_request_economics(
    *,
    embedding_model: str,
    llm_model: str,
    query_text: str,
    context_tokens: int,
    compressed_tokens: int,
    tokens_saved: int,
    llm_context_text: str,
    embedded: bool,
    overrides_json: str = "",
) -> RequestEconomics:
    """Assemble a ``RequestEconomics`` from values the gateway already has.

    ``embedded`` is True when the read path actually embedded the query (i.e.
    retrieval ran in a non-fallback, non-bypassed mode). Compression token counts
    come from the existing ``Compression`` result; pass equal context/compressed
    and 0 saved when compression is off.
    """
    embedding_tokens = estimate_tokens(query_text) if embedded else 0
    # The LLM "input" is the composed (possibly compressed) context plus the user
    # message — an advisory estimate of prompt size.
    llm_input_tokens = estimate_tokens(llm_context_text) + estimate_tokens(query_text)

    embedding_cost = estimate_cost_usd(
        embedding_model, embedding_tokens, kind="embedding", overrides_json=overrides_json
    )
    llm_input_cost = estimate_cost_usd(
        llm_model, llm_input_tokens, kind="input", overrides_json=overrides_json
    )
    # Savings are valued at the LLM input rate (compression shrinks the prompt).
    cost_saved = estimate_cost_usd(
        llm_model, tokens_saved, kind="input", overrides_json=overrides_json
    )

    priced = (
        price_per_1m(embedding_model, overrides_json=overrides_json) is not None
        or price_per_1m(llm_model, overrides_json=overrides_json) is not None
    )

    return RequestEconomics(
        embedding_model=embedding_model,
        llm_model=llm_model,
        embedding_tokens=embedding_tokens,
        context_tokens=context_tokens,
        compressed_tokens=compressed_tokens,
        tokens_saved=tokens_saved,
        llm_input_tokens=llm_input_tokens,
        estimated_cost_usd=round(embedding_cost + llm_input_cost, 8),
        cost_saved_usd=cost_saved,
        priced=priced,
    )
