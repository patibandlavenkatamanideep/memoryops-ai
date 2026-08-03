"""Deterministic semantic-pattern and structural sensitivity classification.

What this is, precisely
-----------------------
Rule-based detection of *disclosures* — a first-person statement that reveals a
credential, an identifier, or a sensitive personal fact. It is **not** medical,
financial, or credential *understanding*: there is no ontology, no model, and no
inference beyond the patterns written here. Describe it as what it is.

Why it exists
-------------
Classification previously matched only *structural* patterns — SSN and card number
shapes, API-key formats. Semantic disclosures scored `low` and were stored `active`:

    "my password is hunter2"            -> low / active
    "my HIV status is positive"         -> low / active
    "I take sertraline for depression"  -> low / active
    "my salary is $250,000"             -> low / active

Every downstream control keys off sensitivity — approval gating, the recall gate's
audience clearance, the admission gate — so for exactly the categories those controls
exist to protect, they were inert. A plaintext password was retrievable into a
`public`-audience response.

Separation of responsibilities
------------------------------
This module **detects and recommends**; it never decides storage. The policy broker
remains authoritative and applies tenant settings, approval configuration, the
governance profile, consent, and temporary-chat behaviour on top. Keeping the
recommendation separate stops the scanner becoming a second policy broker.

Known limits (stated rather than papered over)
----------------------------------------------
Pattern rules miss paraphrase, other languages, obfuscation, and unusual phrasing.
A rule that fires is high-confidence; silence is *not* evidence of safety. Broadening
recall belongs with evaluation evidence, not with more unreviewed regexes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schemas.memory import Sensitivity

# ── dispositions, most restrictive first ─────────────────────────────────────
BLOCK = "BLOCK"
PENDING_APPROVAL = "PENDING_APPROVAL"
SAVE = "SAVE"

_DISPOSITION_RANK = {BLOCK: 2, PENDING_APPROVAL: 1, SAVE: 0}
_SENSITIVITY_RANK = {Sensitivity.high: 2, Sensitivity.medium: 1, Sensitivity.low: 0}


@dataclass(frozen=True)
class SensitivityFinding:
    """One rule match. Content-free: it names *what* matched, never the value."""

    category: str
    rule_id: str
    sensitivity: Sensitivity
    recommended_disposition: str
    confidence: float = 1.0


@dataclass(frozen=True)
class SensitivityAssessment:
    """Aggregate of every finding, with deterministic precedence applied."""

    findings: tuple[SensitivityFinding, ...] = field(default_factory=tuple)
    sensitivity: Sensitivity = Sensitivity.low
    recommended_disposition: str = SAVE

    @property
    def categories(self) -> tuple[str, ...]:
        # Deduplicated, order-stable — safe to put in audit metadata.
        seen: dict[str, None] = {}
        for f in self.findings:
            seen.setdefault(f.category, None)
        return tuple(seen)

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(f.rule_id for f in self.findings)


# ── framing guard ────────────────────────────────────────────────────────────
# A sensitive keyword is not a disclosure. These forms discuss a topic rather than
# reveal a fact about the speaker, and must never classify as sensitive:
#
#   "How should password hashing work?"        (question / educational)
#   "Sertraline is a commonly prescribed …"    (third-person description)
#   "I am reading research about HIV"          (study framing)
#   "This document explains bank routing …"    (documentation framing)
#
# The rules below are written to require first-person disclosure, so this is
# defence in depth rather than the only guard.
_EDUCATIONAL_FRAMING = [
    re.compile(r"^\s*(?:how|what|why|when|where|which|who|can|should|does|do|is|are)\b"
               r"[^.?!]*\?", re.IGNORECASE),
    re.compile(r"\b(?:reading|read|researching|research|studying|study|learning|learn)\b"
               r"[^.?!]{0,40}\b(?:about|on|into)\b", re.IGNORECASE),
    re.compile(r"\b(?:this|the)\s+(?:document|article|paper|guide|post|book)\b",
               re.IGNORECASE),
    re.compile(r"\b(?:commonly|widely|typically|generally)\s+(?:prescribed|used|known)\b",
               re.IGNORECASE),
    re.compile(r"\b(?:average|median|typical)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+(?:to|do|does|should)\b", re.IGNORECASE),
]


def _is_educational(text: str) -> bool:
    return any(p.search(text) for p in _EDUCATIONAL_FRAMING)


# Sentence terminators, semicolons, and contrastive conjunctions. Clauses are the
# unit of classification: an educational or memory-control clause must not exempt a
# *separate* disclosure clause in the same message.
_CLAUSE_SPLIT = re.compile(
    r"(?<=[.!?])\s+"                      # sentence boundary
    r"|\s*;\s*"                           # semicolon
    r"|,\s+(?=but\b|however\b|although\b|though\b)",  # contrastive comma
    re.IGNORECASE,
)


def split_clauses(text: str) -> list[str]:
    """Split into clauses for independent classification.

    Classifying the whole message at once let one clause exempt another:

        "I am reading research about HIV. My HIV status is positive."
        "What is the average software engineer salary? My salary is $250,000."

    The educational framing matched somewhere in the text, so the entire message
    returned an empty assessment and the real disclosure went unclassified.
    """
    return [c.strip() for c in _CLAUSE_SPLIT.split(text) if c and c.strip()]


# ── rules ────────────────────────────────────────────────────────────────────
# Each rule requires first-person ownership AND a disclosure verb AND a value or
# condition, so a bare keyword cannot trigger it. `\b` boundaries throughout so
# "password manager" or "passport control" do not match a password rule.

# "is" / "=" / ":" followed by a non-space value.
_DISCLOSES = r"\s*(?:is|are|was|=|:)\s*\S+"

_RULES: list[tuple[str, str, Sensitivity, str, re.Pattern[str]]] = [
    # ── credentials → BLOCK ─────────────────────────────────────────────────
    (
        "credential",
        "credential.password_first_person",
        Sensitivity.high,
        BLOCK,
        # `(?!\s*manager)` so "my password manager is 1Password" is a tool
        # preference, not a credential disclosure.
        re.compile(
            r"\bmy\s+(?:password|passcode|passphrase)\b(?!\s*manager)" + _DISCLOSES,
            re.IGNORECASE,
        ),
    ),
    (
        "credential",
        "credential.pin_first_person",
        Sensitivity.high,
        BLOCK,
        re.compile(r"\bmy\s+(?:pin|pin\s+code|passcode)\b" + _DISCLOSES, re.IGNORECASE),
    ),
    (
        "credential",
        "credential.security_answer",
        Sensitivity.high,
        BLOCK,
        re.compile(
            r"\bmy\s+security\s+(?:answer|question\s+answer)\b" + _DISCLOSES,
            re.IGNORECASE,
        ),
    ),
    # ── recovery secrets → BLOCK ────────────────────────────────────────────
    (
        "recovery_secret",
        "recovery_secret.code_first_person",
        Sensitivity.high,
        BLOCK,
        re.compile(
            r"\bmy\s+(?:recovery|backup|one[- ]?time|2fa|mfa)\s+"
            r"(?:code|codes|key)\b" + _DISCLOSES,
            re.IGNORECASE,
        ),
    ),
    (
        "recovery_secret",
        "recovery_secret.seed_phrase",
        Sensitivity.high,
        BLOCK,
        re.compile(
            r"\bmy\s+(?:seed|recovery|mnemonic)\s+phrase\b" + _DISCLOSES, re.IGNORECASE
        ),
    ),
    # ── payment information → BLOCK ─────────────────────────────────────────
    (
        "payment",
        "payment.account_first_person",
        Sensitivity.high,
        BLOCK,
        re.compile(
            r"\bmy\s+(?:bank\s+account|account|routing|card|credit\s+card|debit\s+card)"
            r"\s+number\b" + _DISCLOSES,
            re.IGNORECASE,
        ),
    ),
    # ── government identifiers → BLOCK ──────────────────────────────────────
    (
        "government_id",
        "government_id.first_person",
        Sensitivity.high,
        BLOCK,
        re.compile(
            r"\bmy\s+(?:social\s+security|ssn|passport|driver'?s?\s+licen[cs]e|"
            r"national\s+insurance|tax\s+id)\s*(?:number|no\.?)?\b" + _DISCLOSES,
            re.IGNORECASE,
        ),
    ),
    # ── medical → high, approval ────────────────────────────────────────────
    (
        "medical",
        "medical.status_disclosure",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(
            r"\bmy\s+(?:hiv|hep(?:atitis)?\s*[abc]?|std|sti|cancer|covid)\s+status\b"
            + _DISCLOSES,
            re.IGNORECASE,
        ),
    ),
    (
        "medical",
        "medical.diagnosis_first_person",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(
            r"\bi\s+(?:was|were|been|have\s+been|am)\s+diagnosed\s+with\b", re.IGNORECASE
        ),
    ),
    (
        "medical",
        "medical.condition_first_person",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(
            r"\bi\s+(?:have|suffer\s+from|live\s+with)\s+"
            r"(?:\w+\s+){0,2}?(?:diabetes|cancer|epilepsy|asthma|hiv|lupus|"
            r"crohn'?s|arthritis)\b",
            re.IGNORECASE,
        ),
    ),
    # ── mental health → high, approval ──────────────────────────────────────
    (
        "mental_health",
        "mental_health.medication_first_person",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(
            r"\bi\s+(?:take|am\s+on|was\s+prescribed|started)\s+"
            r"(?:\w+\s+){0,2}?(?:sertraline|fluoxetine|citalopram|escitalopram|"
            r"venlafaxine|bupropion|lithium|quetiapine|olanzapine|prozac|zoloft|"
            r"lexapro)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "mental_health",
        "mental_health.treatment_first_person",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(
            r"\bi\s+(?:take|am\s+on|was\s+prescribed|started)\b[^.?!]{0,40}?"
            r"\bfor\s+(?:my\s+)?(?:depression|anxiety|bipolar|ptsd|ocd|adhd)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "mental_health",
        "mental_health.condition_first_person",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(
            r"\bi\s+(?:have|was\s+diagnosed\s+with|suffer\s+from|struggle\s+with)\s+"
            r"(?:\w+\s+){0,2}?(?:depression|anxiety|bipolar|schizophrenia|ptsd|ocd)\b",
            re.IGNORECASE,
        ),
    ),
    # ── financial condition → high, approval ────────────────────────────────
    (
        "financial",
        "financial.amount_first_person",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(
            r"\bmy\s+(?:salary|income|bank\s+balance|account\s+balance|net\s+worth|"
            r"credit\s+score|rent|mortgage)\b" + _DISCLOSES,
            re.IGNORECASE,
        ),
    ),
    (
        "financial",
        "financial.debt_first_person",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(r"\bi\s+owe\b[^.?!]{0,30}?[\d$]", re.IGNORECASE),
    ),
    # ── precise private location → high, approval ───────────────────────────
    (
        "location",
        "location.home_address_first_person",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(
            r"\bmy\s+(?:home\s+|current\s+|street\s+)?address\b" + _DISCLOSES,
            re.IGNORECASE,
        ),
    ),
    # ── biometrics → high, approval ─────────────────────────────────────────
    (
        "biometric",
        "biometric.first_person",
        Sensitivity.high,
        PENDING_APPROVAL,
        re.compile(
            r"\bmy\s+(?:fingerprint|face\s+(?:id|template|scan)|voiceprint|retina\s+scan|"
            r"iris\s+scan)\b" + _DISCLOSES,
            re.IGNORECASE,
        ),
    ),
]


def classify(text: str) -> SensitivityAssessment:
    """Classify text into a content-free assessment.

    Returns an empty, ``SAVE``/``low`` assessment when nothing matches — silence is
    "no rule fired", not a guarantee the text is safe.
    """
    if not text or not text.strip():
        return SensitivityAssessment()

    # Per clause: a question or topic description is not a disclosure about the
    # speaker, but it only exempts *itself*. Whole-message framing checks let
    # "I am reading research about HIV. My HIV status is positive." pass as safe.
    findings: list[SensitivityFinding] = []
    seen_rules: set[str] = set()
    for clause in split_clauses(text) or [text]:
        if _is_educational(clause):
            continue
        for category, rule_id, sensitivity, disposition, pattern in _RULES:
            if rule_id in seen_rules:
                continue
            if pattern.search(clause):
                seen_rules.add(rule_id)
                findings.append(
                    SensitivityFinding(
                        category=category,
                        rule_id=rule_id,
                        sensitivity=sensitivity,
                        recommended_disposition=disposition,
                    )
                )

    if not findings:
        return SensitivityAssessment()

    # Deterministic precedence: BLOCK > PENDING_APPROVAL > SAVE, high > medium > low.
    disposition = max(
        (f.recommended_disposition for f in findings), key=lambda d: _DISPOSITION_RANK[d]
    )
    sensitivity = max((f.sensitivity for f in findings), key=lambda s: _SENSITIVITY_RANK[s])
    return SensitivityAssessment(
        findings=tuple(findings),
        sensitivity=sensitivity,
        recommended_disposition=disposition,
    )


# ── memory-control instructions ──────────────────────────────────────────────
# "do not remember my password" is an instruction *about* memory, not a fact to
# store. It must produce no memory at all — storing it as a high-sensitivity record
# would be the same disclosure by another route, and returning BLOCK alone would
# still be wrong, since there is nothing here that should have been a candidate.
_MEMORY_CONTROL = [
    re.compile(
        r"\b(?:do\s*n[o']?t|don'?t|never|please\s+do\s*n[o']?t|stop)\b[^.?!]{0,40}?"
        r"\b(?:remember|save|store|keep|record|memoris?e|memoriz?e|retain)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bi\s+do\s*n[o']?t\s+want\s+you\s+to\s+"
        r"(?:remember|save|store|keep|record|retain)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:forget|erase|delete|remove)\b[^.?!]{0,30}?\bmy\b", re.IGNORECASE),
]


# `forget my X` / `delete my X` asks to remove something already stored — a
# *deletion* request, distinct from `do not remember my X`, which only prevents new
# persistence. Both suppress a new candidate; only the first should eventually
# invoke the governed forget workflow. Separated here so that distinction is
# available rather than conflated.
_FORGET_REQUEST = re.compile(
    r"\b(?:forget|erase|delete|remove)\b[^.?!]{0,30}?\bmy\b", re.IGNORECASE
)


def is_memory_control_instruction(text: str) -> bool:
    """True when *any clause* asks the assistant not to remember (or to forget).

    Clause-scoped for the same reason as `classify`: whole-message matching let one
    instruction suppress an unrelated fact in the same turn.
    """
    return any(_clause_is_memory_control(c) for c in (split_clauses(text) or [text]))


def _clause_is_memory_control(clause: str) -> bool:
    return any(p.search(clause) for p in _MEMORY_CONTROL)


def is_forget_request(text: str) -> bool:
    """True for `forget my salary` — a request to remove *existing* memory.

    Distinct from `do not remember my salary`, which only prevents new persistence.
    This currently suppresses the new candidate like any other memory-control
    instruction; routing it into the governed forget workflow (legal hold,
    `deleted_at`, tombstone, lineage, deletion audit) is follow-up work and is
    deliberately **not** done here — silently deleting on a chat phrase would be a
    destructive action taken without the deletion path's guarantees.
    """
    return any(_FORGET_REQUEST.search(c) for c in (split_clauses(text) or [text]))


def strip_memory_control_clauses(text: str) -> str:
    """Return the text with memory-control clauses removed.

    Discarding the whole message suppressed legitimate facts stated alongside an
    instruction:

        "Do not remember my password, but remember that I prefer dark mode."

    Only the instruction clause is dropped; the preference survives to extraction.
    """
    clauses = split_clauses(text)
    if not clauses:
        return "" if _clause_is_memory_control(text) else text
    kept = [c for c in clauses if not _clause_is_memory_control(c)]
    return " ".join(kept).strip()
