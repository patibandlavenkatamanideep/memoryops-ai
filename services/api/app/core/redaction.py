"""Secret / PII detection and redaction, plus a prompt-injection heuristic.

This is the safety substrate the Policy Broker (ADR-003) builds on. Detectors are
deterministic so hard rules ("block API keys") are verifiable — unlike an LLM
judge. Defense in depth: regex secrets + PII classification + injection guard.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schemas.memory import Sensitivity
from .sensitivity import BLOCK, SensitivityAssessment, classify

# ── Secret patterns ──────────────────────────────────────────────────────────
# Each entry: (label, compiled regex). Order is not significant.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{12,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("gcp_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("bearer", re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.IGNORECASE)),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("generic_secret", re.compile(
        r"\b(?:api[_-]?key|secret|password|passwd|token|client[_-]?secret)\b\s*[:=]\s*\S{6,}",
        re.IGNORECASE,
    )),
]

# ── PII patterns (elevate sensitivity, do not necessarily block) ─────────────
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("phone", re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
]

# ── Prompt-injection / memory-poisoning heuristics ───────────────────────────
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore (?:all |the )?(?:previous|prior|above) instructions", re.IGNORECASE),
    re.compile(r"disregard (?:all |the )?(?:previous|prior) (?:instructions|rules)", re.IGNORECASE),
    re.compile(r"\bsystem prompt\b", re.IGNORECASE),
    re.compile(r"you are now (?:a|an|in)\b", re.IGNORECASE),
    re.compile(r"\b(?:jailbreak|DAN mode)\b", re.IGNORECASE),
]


@dataclass
class ScanResult:
    has_secret: bool = False
    secret_labels: list[str] = field(default_factory=list)
    pii_labels: list[str] = field(default_factory=list)
    injection: bool = False
    #: Semantic-pattern classification (app/core/sensitivity.py). Structural
    #: patterns above catch *shapes* — key formats, SSN and card digits. They said
    #: nothing about "my password is hunter2" or "my HIV status is positive", which
    #: scored `low` and were stored active, leaving every sensitivity-keyed control
    #: inert for exactly the categories they exist to protect.
    assessment: SensitivityAssessment = field(default_factory=SensitivityAssessment)

    @property
    def sensitivity(self) -> str:
        if self.has_secret:
            return "high"
        # A semantic disclosure outranks a structural PII hit.
        if self.assessment.sensitivity is Sensitivity.high:
            return "high"
        if self.pii_labels:
            return "medium"
        if self.assessment.sensitivity is Sensitivity.medium:
            return "medium"
        return "low"

    @property
    def blocks(self) -> bool:
        """Deterministic hard-block signal: a secret shape *or* a disclosed credential.

        The broker still decides; this only reports what detection recommends.
        """
        return self.has_secret or self.assessment.recommended_disposition == BLOCK


def scan(text: str) -> ScanResult:
    """Classify a piece of candidate memory content."""
    result = ScanResult()
    for label, pat in _SECRET_PATTERNS:
        if pat.search(text):
            result.has_secret = True
            result.secret_labels.append(label)
    for label, pat in _PII_PATTERNS:
        if pat.search(text):
            # credit_card regex is broad; only flag if it really looks card-like.
            if label == "credit_card":
                digits = re.sub(r"\D", "", pat.search(text).group())
                if not 13 <= len(digits) <= 16:
                    continue
            result.pii_labels.append(label)
    result.injection = any(p.search(text) for p in _INJECTION_PATTERNS)
    result.assessment = classify(text)
    return result


def redact_secrets(text: str) -> str:
    """Replace any secret-looking substrings with a placeholder (for logs)."""
    if not text:
        return text
    redacted = text
    for _, pat in _SECRET_PATTERNS:
        redacted = pat.sub("«redacted-secret»", redacted)
    return redacted
