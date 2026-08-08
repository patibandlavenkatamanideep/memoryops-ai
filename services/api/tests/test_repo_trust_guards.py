"""The structural guards, and proof each one fails on the mistake it describes.

A guard nobody has watched fail is a guard nobody knows works. Every check here has
two halves: the repository is clean today, and a synthetic tree containing the
specific bad edit is *rejected*. The negative half is the one that matters — the
positive half passes just as well when the guard is broken.

Each guard takes a `root`, so the negative tests build a small tree in `tmp_path`
rather than editing the repository.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from repo_trust_guards import (  # noqa: E402
    GUARDS,
    check_no_committed_secret_literals,
    check_no_demo_identity_in_server_code,
    check_no_retired_infrastructure,
    check_no_sys_path_mutation,
    run_all,
)


def _write(root: Path, relative: str, source: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


# ── the repository is clean ─────────────────────────────────────────────────
def test_the_repository_passes_every_guard():
    findings = run_all(REPO_ROOT)
    assert not findings, "\n".join(str(f) for f in findings)


def test_every_guard_is_registered_and_callable():
    """A guard that exists but is not in GUARDS never runs in CI."""
    assert set(GUARDS) == {
        "sys-path-mutation",
        "committed-secret-literal",
        "demo-identity-in-server-code",
        "retired-infrastructure",
    }
    for name, guard in GUARDS.items():
        assert callable(guard), name


# ── guard 1: sys.path ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "statement",
    [
        "sys.path.insert(0, '/somewhere')",
        "sys.path.append('/somewhere')",
        "sys.path.extend(['/somewhere'])",
        "sys.path = ['/somewhere']",
        "sys.path += ['/somewhere']",
    ],
)
def test_a_sys_path_mutation_in_shipped_code_is_rejected(tmp_path, statement):
    _write(
        tmp_path,
        "services/worker/thing.py",
        f"import sys\n\n{statement}\n",
    )
    findings = check_no_sys_path_mutation(tmp_path)
    assert findings, f"not caught: {statement}"
    assert findings[0].guard == "sys-path-mutation"


def test_prose_about_sys_path_is_not_a_finding(tmp_path):
    """The reason this is AST-based.

    Every one of these mentions `sys.path.insert()` while doing nothing of the kind,
    and all three exist in this repository — the worker's pyproject and Dockerfile
    explain that the practice was removed. A string search fired on the explanation.
    """
    _write(
        tmp_path,
        "services/worker/thing.py",
        '"""This module used to call sys.path.insert() at import time."""\n'
        "# no sys.path.append() remains anywhere in a production entrypoint\n"
        "MESSAGE = 'sys.path.insert(0, x) is banned here'\n",
    )
    assert check_no_sys_path_mutation(tmp_path) == []


def test_tests_and_scripts_may_still_adjust_sys_path(tmp_path):
    """They are not shipped, and reaching a sibling package is legitimate — this
    very file does it to import the guards."""
    _write(tmp_path, "services/worker/test_thing.py", "import sys\nsys.path.insert(0, 'x')\n")
    _write(tmp_path, "scripts/tool.py", "import sys\nsys.path.insert(0, 'x')\n")
    assert check_no_sys_path_mutation(tmp_path) == []


def test_the_worker_no_longer_rewrites_its_import_path():
    """The live instance this guard was written from.

    `services/worker/jobs.py` inserted `../api` into `sys.path` at import time while
    `services/worker/pyproject.toml` stated that no such call remained in a production
    entrypoint. The file ships in the worker image, so the claim was false wherever it
    was read.

    Asserted through the guard rather than by searching for the string: the file now
    carries a comment *explaining* that it used to call `sys.path.insert()`, and an
    earlier draft of this very test failed on that comment — the same false positive
    the guard is built to avoid, reproduced inside its own test suite.
    """
    worker = REPO_ROOT / "services" / "worker"
    assert check_no_sys_path_mutation(REPO_ROOT) == []
    assert "sys.path" in (worker / "jobs.py").read_text(), (
        "the comment recording why the mutation was removed is gone — keep it, and "
        "keep asserting through the parser rather than through a substring"
    )


# ── guard 2: committed secrets ──────────────────────────────────────────────
# The bad-input fixtures for the secret guard are themselves assembled at runtime.
#
# Writing them inline committed two credential-shaped strings, and gitleaks flagged
# this commit — the exact mistake this guard exists to prevent, made while writing the
# guard. Worth recording rather than quietly fixing: the pull toward "it's only a test
# fixture" is what put the earlier literals in the tree, and a scanner cannot tell a
# guard's negative case from a live key.
_AWS = "AKIA" + "IOSFODNN7" + "EXAMPLE"
_GITHUB = "ghp_" + "0123456789" + "abcdefghijklmnopqrstuvwx"
_OPENAI = "sk-" + "live" + "0123456789abcdef"
_DENSE = "abcdef" + "0123456789"


@pytest.mark.parametrize(
    "source",
    [
        f'api_key = "{_AWS}"',
        f'client_secret = "{_DENSE}"',
        'SIGNING_KEY = "hunter2hunter2"',
        f'connect(token="{_GITHUB}")',
        f'x = "{_OPENAI}"',
    ],
)
def test_a_committed_credential_literal_is_rejected(tmp_path, source):
    _write(tmp_path, "services/api/tests/test_thing.py", source + "\n")
    findings = check_no_committed_secret_literals(tmp_path)
    assert findings, f"not caught: {source}"
    assert findings[0].guard == "committed-secret-literal"


@pytest.mark.parametrize("template", [
    'message = "My API key is {key} please remember it"',
    'CandidateMemory(content="my key is {key} keep it safe")',
    'payload = \'{{"content": "API key is {key}"}}\'',
    'chat(gateway, "Save this: {key} is my key.")',
])
def test_a_credential_embedded_in_a_sentence_is_rejected(tmp_path, template):
    """The gap a whole-value match leaves open.

    A fixture usually arrives *inside* a sentence, because that is how a user would
    paste a key into a chat — and the secret-detection tests are exactly where such
    sentences live. None of these is a bare token, none is assigned to a
    credential-named variable, and every one contains whitespace, so all three of the
    earlier heuristics let them through. Six were in this repository when the token
    search was added.
    """
    source = template.format(key=_OPENAI)
    _write(tmp_path, "services/api/tests/test_thing.py", source + "\n")
    findings = check_no_committed_secret_literals(tmp_path)
    assert findings, f"not caught: {source}"
    assert "credential token" in findings[0].detail


@pytest.mark.parametrize("kind", ["module", "function", "class"])
def test_a_docstring_describing_a_credential_is_not_a_finding(tmp_path, kind):
    """Excluded structurally, not by pattern.

    `_secret_fixtures.py` explains the `sk-` shape in its own docstring, and this
    guard's module docstring does the same. Deciding prose-versus-code by inspecting
    the text would be the grep-shaped mistake these guards exist to avoid; the parser
    already knows which constants are docstrings.
    """
    body = f'"""An example credential looks like {_OPENAI} in prose."""'
    sources = {
        "module": body + "\n",
        "function": f"def f():\n    {body}\n    return 1\n",
        "class": f"class C:\n    {body}\n",
    }
    _write(tmp_path, "services/api/tests/test_thing.py", sources[kind])
    assert check_no_committed_secret_literals(tmp_path) == []


def test_a_runtime_assembled_token_is_not_a_finding(tmp_path):
    """The prescribed fix must not itself trip the guard: concatenation leaves no
    constant containing the token."""
    _write(
        tmp_path,
        "services/api/tests/test_thing.py",
        'KEY = "sk-" + "live" + "0123456789abcdef"\n'
        'message = f"My API key is {KEY} please remember it"\n',
    )
    assert check_no_committed_secret_literals(tmp_path) == []


def test_a_token_inside_a_longer_identifier_is_not_a_finding(tmp_path):
    """Boundaries: `sk-live…` embedded in a longer word is not a credential."""
    _write(
        tmp_path,
        "services/api/tests/test_thing.py",
        'name = "prefix-sk-live0123456789abcdef-suffix"\n',
    )
    assert check_no_committed_secret_literals(tmp_path) == []


def test_this_files_own_fixtures_contain_no_committed_literal():
    """The guard, applied to its own test suite.

    An inline fixture here would be a committed secret-shaped literal in exactly the
    file that argues against them.
    """
    findings = check_no_committed_secret_literals(Path(__file__).parent)
    assert not findings, "\n".join(str(f) for f in findings)


@pytest.mark.parametrize(
    "source",
    [
        # Assembled at runtime — the pattern `tests/_secret_fixtures.py` uses.
        'api_key = "sk" + "-" + "live" + "0123456789"',
        # A sentence that happens to be called `secret`: memory content in deletion
        # tests, named for what it means to the user rather than what it looks like.
        'secret = "the acquisition closes on the fourteenth"',
        # Placeholders and references.
        'password = ""',
        'api_key = "${OPENAI_API_KEY}"',
        'token = "<redacted>"',
        'secret = os.environ["X"]',
    ],
)
def test_legitimate_credential_handling_is_not_a_finding(tmp_path, source):
    _write(tmp_path, "services/api/tests/test_thing.py", "import os\n" + source + "\n")
    assert check_no_committed_secret_literals(tmp_path) == [], source


def test_the_runtime_assembled_fixtures_are_themselves_clean():
    """The module that exists to avoid literals must not contain one."""
    fixtures = REPO_ROOT / "services" / "api" / "tests" / "_secret_fixtures.py"
    assert fixtures.exists()
    assert check_no_committed_secret_literals(fixtures.parent) == []


# ── guard 3: demo identity ──────────────────────────────────────────────────
def test_demo_identity_in_server_code_is_rejected(tmp_path):
    _write(
        tmp_path,
        "apps/web/app/api/proxy/route.ts",
        'export async function GET() {\n  const tenant = "tenant_demo";\n  return tenant;\n}\n',
    )
    findings = check_no_demo_identity_in_server_code(tmp_path)
    assert findings
    assert findings[0].guard == "demo-identity-in-server-code"


def test_prose_about_the_demo_persona_is_not_a_finding(tmp_path):
    """`lib/api.ts` documents the `DEMO_TENANT` constants it no longer exports, and
    the BFF explains why the browser must not choose its own scope. Both mention the
    literals; neither uses them."""
    _write(
        tmp_path,
        "apps/web/lib/api.ts",
        "/**\n"
        " * Previously exported hardcoded DEMO_TENANT / DEMO_USER constants, which\n"
        ' * pinned every request to "tenant_demo".\n'
        " */\n"
        "// DEMO_TENANT is gone; identity comes from the server.\n"
        "export const base = '/api/memoryops';\n",
    )
    assert check_no_demo_identity_in_server_code(tmp_path) == []


def test_a_demo_literal_inside_a_string_still_counts(tmp_path):
    """Comment-stripping must not become string-stripping: the value is the bug."""
    _write(
        tmp_path,
        "apps/web/lib/scope.ts",
        'export const fallback = { tenantId: "tenant_demo" }; // not a comment\n',
    )
    assert check_no_demo_identity_in_server_code(tmp_path)


def test_the_demo_mode_module_itself_is_allowed(tmp_path):
    """`lib/identity.ts` *implements* demo mode and refuses it in production. Banning
    the literal there would ban the feature."""
    _write(
        tmp_path,
        "apps/web/lib/identity.ts",
        'const demo = { tenantId: "tenant_demo", userId: "user_demo" };\n',
    )
    assert check_no_demo_identity_in_server_code(tmp_path) == []


# ── guard 4: retired infrastructure ─────────────────────────────────────────
@pytest.mark.parametrize(
    "source",
    ["import redis", "from redis import Redis", "import redis.asyncio", "import celery"],
)
def test_a_retired_dependency_returning_is_rejected(tmp_path, source):
    _write(tmp_path, "services/api/app/thing.py", source + "\n")
    findings = check_no_retired_infrastructure(tmp_path)
    assert findings, f"not caught: {source}"
    assert findings[0].guard == "retired-infrastructure"


def test_a_retired_setting_returning_is_rejected(tmp_path):
    _write(
        tmp_path,
        "services/api/app/core/config.py",
        "class Settings:\n    redis_url: str = ''\n",
    )
    findings = check_no_retired_infrastructure(tmp_path)
    assert findings
    assert "redis_url" in findings[0].detail


def test_prose_about_a_retired_dependency_is_not_a_finding(tmp_path):
    """`test_no_unused_infrastructure.py` explains at length why Redis was removed."""
    _write(
        tmp_path,
        "services/api/app/thing.py",
        '"""Redis was declared but never used, so `import redis` appears nowhere."""\n'
        "# We deliberately do not import redis here.\n"
        "NOTE = 'from redis import Redis'\n",
    )
    assert check_no_retired_infrastructure(tmp_path) == []


def test_a_similarly_named_module_is_not_confused_for_the_retired_one(tmp_path):
    """`redis_notes` is not `redis`; import matching is on the module, not a substring."""
    _write(tmp_path, "services/api/app/thing.py", "import redis_notes\nfrom redisx import y\n")
    assert check_no_retired_infrastructure(tmp_path) == []
