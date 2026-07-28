"""Deterministic matching + scoring tests (offline)."""

from __future__ import annotations

from research.extraction_eval.matching import match_atoms, pair_score
from research.extraction_eval.schema import ExtractionOutput, Gold, GoldAtom, MemoryAtom, PolicyDisposition
from research.extraction_eval.scoring import ScoringConfig, score_case


def _gold(*atoms, noop=False):
    return Gold(expected_noop=noop, atoms=list(atoms))


def _ga(text, aid="a", phr=None, mtype="preference", op="create", disp="save", store=True):
    return GoldAtom(atom_id=aid, memory_text=text, accepted_phrasings=phr or [], memory_type=mtype,
                    operation=op, policy_disposition=disp, should_store=store, source_turn_ids=["t1"])


def _out(*texts, **meta):
    return ExtractionOutput(memories=[MemoryAtom(memory_text=t, memory_type=meta.get("mtype", "preference"),
                                                 operation=meta.get("op", "create"),
                                                 policy_disposition=meta.get("disp", "save"),
                                                 should_store=meta.get("store", True)) for t in texts])


def _score(out, gold, **kw):
    return score_case(out, gold, provider="p", case_id="c", category="single_memory", repetition=1,
                      cfg=ScoringConfig(threshold=0.85), **kw)


def test_exact_match():
    s = _score(_out("User prefers metric units."), _gold(_ga("User prefers metric units.")))
    assert (s.tp, s.fp, s.fn) == (1, 0, 0) and s.exact_set_match


def test_alias_match():
    s = _score(_out("User preference: metric units."),
               _gold(_ga("User prefers metric units.", phr=["User preference: metric units."])))
    assert s.tp == 1 and s.fp == 0


def test_multi_atom_matching():
    gold = _gold(_ga("User likes tea.", aid="a"), _ga("User moved to Boston.", aid="b"))
    s = _score(_out("User likes tea.", "User moved to Boston."), gold)
    assert (s.tp, s.fp, s.fn) == (2, 0, 0)


def test_false_positive():
    s = _score(_out("User likes tea.", "User owns a boat."), _gold(_ga("User likes tea.")))
    assert s.tp == 1 and s.fp == 1 and s.fn == 0


def test_false_negative():
    gold = _gold(_ga("User likes tea.", aid="a"), _ga("User owns a boat.", aid="b"))
    s = _score(_out("User likes tea."), gold)
    assert s.tp == 1 and s.fn == 1


def test_noop_scoring():
    s = _score(_out(), _gold(noop=True))
    assert s.noop_correct is True and s.fp == 0
    s2 = _score(_out("User likes tea."), _gold(noop=True))
    assert s2.noop_correct is False and s2.fp == 1  # any atom on a no-op is a false memory


def test_update_operation_scoring():
    gold = _gold(_ga("User's favorite color is green.", op="update", disp="update_existing"))
    s = _score(_out("User's favorite color is green.", op="update", disp="update_existing"), gold)
    assert s.tp == 1 and s.operation_correct == 1 and s.policy_correct == 1


def test_policy_disposition_scored_separately():
    # Correct atom text but wrong disposition -> matched (extraction ok) but policy wrong.
    gold = _gold(_ga("User shared an AWS key.", disp="block", store=False))
    s = _score(_out("User shared an AWS key.", disp="save", store=True), gold)
    assert s.tp == 1 and s.policy_correct == 0 and s.should_store_correct == 0


def test_sensitive_correctly_blocked_gets_extraction_and_policy_credit():
    # A sensitive candidate correctly extracted AND marked block/should_store=false is an
    # extraction success and a policy success — never scored as a stored memory (#6).
    gold = _gold(_ga("User shared an AWS key.", disp="block", store=False))
    s = _score(_out("User shared an AWS key.", disp="block", store=False), gold)
    assert s.tp == 1  # extraction credit
    assert s.policy_correct == 1  # policy credit (block matched)
    assert s.should_store_correct == 1  # correctly NOT stored
    assert s.fp == 0 and s.fn == 0
    # `should_store=false` is tracked, not folded into any "stored" count.
    assert not s.expected_noop


def test_error_case_is_not_zero():
    s = _score(None, _gold(_ga("x")), error_class="refusal")
    assert s.scored is False and s.error_class == "refusal"


def test_bipartite_prefers_exact_over_lexical():
    # Two golds; one pred exactly matches gold B — greedy must pair exact first.
    gold = _gold(_ga("User likes green tea very much.", aid="a"), _ga("User owns a red car.", aid="b"))
    res = match_atoms(["User owns a red car."], gold.atoms, threshold=0.85)
    assert len(res.matches) == 1 and res.matches[0].gold_index == 1 and res.matches[0].is_exact


def test_pair_score_below_threshold_is_zero():
    score = pair_score("completely different sentence", "User prefers metric units.", [], threshold=0.85)
    assert score == 0.0
