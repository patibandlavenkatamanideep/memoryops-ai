"""Read-time sensitivity for memory that predates the classifier.

The problem
-----------
Semantic classification runs at *write* time — on creation and on a governed
content edit. Rows stored before it existed keep whatever label they were given:

    content:     "my password is hunter2"
    sensitivity: low
    status:      active

Nothing rewrites that on upgrade, so the headline protection would apply only to
content entering after the change. A pre-existing credential row was verified to
still reach a `public`-audience response with its full source excerpt.

The fix
-------
The read path combines the *stored* label with a *current* classification of the
content and uses whichever is higher. A row mislabelled at write time is therefore
gated correctly on every read, immediately after deploy and with no migration.

Deliberately **not** a write. Reads must not mutate rows: it would turn every query
into a write, produce audit events with no actor, and race with concurrent edits.
Persisting the corrected label — with audit evidence — belongs to a reclassification
worker, which can then also record *why* each row changed.

Cost note: this is a deterministic regex pass over already-loaded content, on the
handful of candidates that survived ranking, so it is proportional to admitted
memories rather than to the store.
"""

from __future__ import annotations

from ..core.sensitivity import classify
from ..db.entities import StoredMemory
from ..schemas.memory import Sensitivity

_RANK = {Sensitivity.low: 0, Sensitivity.medium: 1, Sensitivity.high: 2}


def effective_sensitivity(memory: StoredMemory) -> Sensitivity:
    """The stored label, raised to the current classification when that is higher.

    Only ever raises. A row explicitly labelled `high` is never lowered because the
    rules happen not to match it — an operator's judgement outranks a pattern's
    silence, and silence is not evidence of safety.
    """
    stored = memory.sensitivity
    detected = classify(memory.content or "").sensitivity
    return detected if _RANK[detected] > _RANK[stored] else stored


def was_reclassified(memory: StoredMemory) -> bool:
    """True when the read-time classification raised the stored label."""
    return effective_sensitivity(memory) is not memory.sensitivity
