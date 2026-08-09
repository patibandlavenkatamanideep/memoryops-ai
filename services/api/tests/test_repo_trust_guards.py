"""The structural guards, and proof each one fails on the mistake it describes.

A guard nobody has watched fail is a guard nobody knows works. Every check here has
two halves: the repository is clean today, and a synthetic tree containing the
specific bad edit is *rejected*. The negative half is the one that matters — the
positive half passes just as well when the guard is broken.

Each guard takes a `root`, so the negative tests build a small tree in `tmp_path`
rather than editing the repository.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from repo_trust_guards import (  # noqa: E402
    CANONICAL_RAILWAY_CONFIGS,
    GUARDS,
    TRANSITIONAL_DUPLICATE_CONFIGS,
    check_no_committed_secret_literals,
    check_no_demo_identity_in_server_code,
    check_no_retired_infrastructure,
    check_no_sys_path_mutation,
    check_railway_deployment_config,
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
        "railway-deployment-config",
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


# ── guard 5: Railway deployment configuration ───────────────────────────────
#
# The two defects below both reached production in v2.4 and were invisible to every
# other gate: a `$PORT` that never expanded, and a health check pointed at a route
# that redirects. Each negative test reproduces one of them exactly.

_VALID_DEPLOY = {
    "api": '{"deploy": {"healthcheckPath": "/healthz", "numReplicas": 1}}',
    "web": '{"deploy": {"healthcheckPath": "/architecture", "numReplicas": 1}}',
    "worker": '{"deploy": {"numReplicas": 1}}',
    "playground": '{"deploy": {"healthcheckPath": "/_stcore/health"}}',
}


def _railway_tree(root: Path, **overrides: str) -> Path:
    """A tree with every canonical config present and valid, minus any overrides."""
    for service, relative in CANONICAL_RAILWAY_CONFIGS.items():
        _write(root, relative, overrides.get(service, _VALID_DEPLOY[service]))
    return root


def test_a_valid_railway_tree_is_clean(tmp_path):
    assert check_railway_deployment_config(_railway_tree(tmp_path)) == []


def test_the_repository_railway_config_is_clean():
    assert check_railway_deployment_config(REPO_ROOT) == []


@pytest.mark.parametrize(
    "start",
    [
        "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
        "npm run start -- --port ${PORT} --hostname 0.0.0.0",
    ],
)
def test_a_literal_port_in_a_start_command_is_rejected(tmp_path, start):
    """The exact v2.4 defect: exec form does not expand `$PORT`."""
    tree = _railway_tree(
        tmp_path, playground=json.dumps({"deploy": {"startCommand": start}})
    )
    findings = check_railway_deployment_config(tree)
    assert any("literal `$PORT`" in f.detail for f in findings)


def test_a_shell_expanded_port_in_the_dockerfile_is_not_a_finding(tmp_path):
    """The playground expands `${PORT:-8501}` via `sh -c` in its Dockerfile CMD.

    The guard inspects Railway configs, not Dockerfiles, so the reference
    implementation for dynamic ports must not trip it.
    """
    tree = _railway_tree(tmp_path)
    _write(
        tree,
        "apps/playground/Dockerfile",
        'CMD ["sh", "-c", "streamlit run app.py --server.port ${PORT:-8501}"]\n',
    )
    assert check_railway_deployment_config(tree) == []


def test_a_root_healthcheck_on_web_is_rejected(tmp_path):
    """`/` answers 307 -> /signin in authenticated mode, so it can never pass."""
    tree = _railway_tree(tmp_path, web='{"deploy": {"healthcheckPath": "/"}}')
    findings = check_railway_deployment_config(tree)
    assert any("307" in f.detail for f in findings)


def test_the_architecture_healthcheck_is_accepted(tmp_path):
    tree = _railway_tree(tmp_path, web='{"deploy": {"healthcheckPath": "/architecture"}}')
    assert check_railway_deployment_config(tree) == []


@pytest.mark.parametrize("service", ["api", "web", "worker"])
def test_a_start_command_override_is_rejected(tmp_path, service):
    """Declaring the launch in both the Dockerfile and the config is how they drift."""
    tree = _railway_tree(tmp_path, **{service: '{"deploy": {"startCommand": "run it"}}'})
    findings = check_railway_deployment_config(tree)
    assert any("Dockerfile CMD is" in f.detail for f in findings)


def test_a_missing_canonical_config_is_rejected(tmp_path):
    tree = _railway_tree(tmp_path)
    (tree / CANONICAL_RAILWAY_CONFIGS["worker"]).unlink()
    findings = check_railway_deployment_config(tree)
    assert any("is missing" in f.detail for f in findings)


def test_the_transitional_api_duplicate_is_accepted(tmp_path):
    """Production still reads services/api/railway.toml; Phase B removes it.

    This is the one permitted duplicate, and it is permitted by name rather than by
    shape so Phase B can delete the exception and get enforcement for free.
    """
    tree = _railway_tree(tmp_path)
    _write(tree, TRANSITIONAL_DUPLICATE_CONFIGS["api"], '[deploy]\nhealthcheckPath = "/healthz"\n')
    assert check_railway_deployment_config(tree) == []


def test_a_duplicate_config_for_any_other_service_is_rejected(tmp_path):
    """The exception is for the API only — web gaining a second source is a finding."""
    tree = _railway_tree(tmp_path)
    _write(tree, "apps/web/railway.toml", '[deploy]\nhealthcheckPath = "/architecture"\n')
    findings = check_railway_deployment_config(tree)
    assert any("competing Railway config sources" in f.detail for f in findings)


def test_the_transitional_toml_is_still_checked_for_a_literal_port(tmp_path):
    """Being a permitted duplicate does not exempt it — it is what production runs."""
    tree = _railway_tree(tmp_path)
    _write(
        tree,
        TRANSITIONAL_DUPLICATE_CONFIGS["api"],
        '[deploy]\nstartCommand = "uvicorn app.main:app --port $PORT"\n',
    )
    findings = check_railway_deployment_config(tree)
    assert any("literal `$PORT`" in f.detail for f in findings)
