#!/usr/bin/env python3
"""Structural guards for regressions this repository has actually had.

Not general linting. Each guard exists because the corresponding mistake was made
here, reached `main`, and was found by reading rather than by a check.

Why AST and tokens rather than grep
-----------------------------------
Every one of these was first attempted as a string search, and every one produced
false positives on prose *about* the problem: a docstring explaining that
`sys.path.insert()` was removed matched a search for `sys.path.insert`, a comment
describing the `DEMO_TENANT` bug matched a search for `DEMO_TENANT`, and a note
saying Redis was dropped matched a search for `redis`. A guard that fires on its own
documentation trains people to ignore it.

So: parse. `ast` for Python structure, `tokenize` for string literals, and
comment-stripping for TypeScript. A guard only reports what the parser says is code.

Each function returns a list of `Finding`; the CLI prints them and exits non-zero.
They take a `root` so tests can point them at synthetic trees and prove the guard
fires — a guard nobody has seen fail is a guard nobody knows works.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Finding:
    guard: str
    path: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.guard}] {self.detail}"


# ── shared helpers ───────────────────────────────────────────────────────────
_SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".next", "dist",
    "build", ".pytest_cache", ".ruff_cache", "site-packages",
}


def _walk(root: Path, suffix: str) -> Iterator[Path]:
    for path in sorted(root.rglob(f"*{suffix}")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path


def _parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _docstring_constants(module: ast.Module) -> set[int]:
    """Node ids of every docstring in a module.

    Docstrings are excluded from credential-token detection *structurally*, not by
    pattern: a docstring describing an example credential is prose, while an ordinary
    runtime string containing one is code. Deciding that by looking at the text would
    be the grep-shaped mistake these guards exist to avoid — `_secret_fixtures.py`
    explains the `sk-` shape in its own docstring.
    """
    ids: set[int] = set()
    for node in ast.walk(module):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


# ── guard 1: runtime code must not rewrite its own import path ───────────────
#: Directories whose contents are shipped and executed as a service.
RUNTIME_TREES = (
    Path("services") / "api" / "app",
    Path("services") / "worker",
    Path("packages") / "memoryops-sdk" / "memoryops",
)


def _is_sys_path(node: ast.expr) -> bool:
    """True for `sys.path`, however `sys` was imported."""
    return isinstance(node, ast.Attribute) and node.attr == "path" and (
        (isinstance(node.value, ast.Name) and node.value.id == "sys")
        or (isinstance(node.value, ast.Attribute) and node.value.attr == "sys")
    )


def check_no_sys_path_mutation(root: Path = REPO) -> list[Finding]:
    """Runtime service code must not mutate `sys.path` to make imports resolve.

    The worker did this to reach the API package without depending on it. A service
    that rewrites its own import path at startup can resolve a *different* dependency
    set than the service it is importing from, and the failure appears as a version
    skew nobody can trace. It is also invisible: `services/worker/pyproject.toml`
    stated the practice had been removed while `jobs.py` still did it.

    Tests and scripts are excluded — they are not shipped, and a test that needs to
    reach a sibling package is doing something legitimate.
    """
    findings: list[Finding] = []
    mutators = {"append", "insert", "extend", "remove", "pop", "clear"}

    for tree_root in RUNTIME_TREES:
        base = root / tree_root
        if not base.exists():
            continue
        for path in _walk(base, ".py"):
            if "test" in path.name or "conftest" in path.name:
                continue
            module = _parse(path)
            if module is None:
                continue
            for node in ast.walk(module):
                # sys.path.insert(...) / .append(...) / ...
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in mutators
                    and _is_sys_path(node.func.value)
                ):
                    findings.append(
                        Finding(
                            "sys-path-mutation",
                            _rel(path, root),
                            node.lineno,
                            f"sys.path.{node.func.attr}() in shipped service code — "
                            "declare a real dependency instead",
                        )
                    )
                # sys.path = ... / sys.path += ... / sys.path[0] = ...
                targets: Iterable[ast.expr] = ()
                if isinstance(node, ast.Assign):
                    targets = node.targets
                elif isinstance(node, ast.AugAssign):
                    targets = (node.target,)
                for target in targets:
                    inner = target.value if isinstance(target, ast.Subscript) else target
                    if _is_sys_path(inner) or _is_sys_path(target):
                        findings.append(
                            Finding(
                                "sys-path-mutation",
                                _rel(path, root),
                                node.lineno,
                                "assignment to sys.path in shipped service code",
                            )
                        )
    return findings


# ── guard 2: no secret-shaped literals in tracked source ─────────────────────
#: Variable/field names that mean "this value is a credential".
_SECRET_NAME = re.compile(
    r"(?:^|_)(?:secret|password|passwd|token|api_?key|access_?key|private_?key|"
    r"signing_?key|client_?secret|credential)s?$",
    re.IGNORECASE,
)
#: A known credential token, matched **anywhere** in a string rather than as the whole
#: value. Fixtures usually arrive inside a sentence — "My API key is sk-… please
#: remember it" is the natural shape for a memory or prompt test, and it escapes both
#: a whole-value match and a credential-named-variable heuristic. Boundaries keep
#: `sk-live…` from matching inside a longer identifier.
_SECRET_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_-])"
    r"(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})"
    r"(?![A-Za-z0-9_-])"
)
#: Values that are obviously not credentials even under a secret-ish name.
_INNOCUOUS = re.compile(r"^(?:|none|null|changeme|\*+|\$\{[^}]*\}|<[^>]*>)$", re.IGNORECASE)


def _is_secretish_value(value: str) -> bool:
    """Whether a literal is plausibly a credential, not merely long.

    Whitespace is the discriminator that matters in practice. A credential is a dense
    token; `secret = "the acquisition closes on the fourteenth"` is a *sentence* — it
    appears in deletion tests where the variable is named for what the memory means to
    the user, not for what the string is. Flagging it would make the guard fire on
    correct code, which is how a guard gets ignored.
    """
    if any(ch.isspace() for ch in value):
        return False
    return len(value) >= 8 and not _INNOCUOUS.match(value) and not value.startswith(("http", "/"))


def check_no_committed_secret_literals(root: Path = REPO) -> list[Finding]:
    """Credential-shaped values must be assembled at runtime, never written literally.

    Tests for secret *detection* need input that looks like a real credential, and
    writing that inline commits a secret-shaped string — which is what scanners exist
    to catch, and they cannot tell a fixture from a live key. Gitleaks flagged exactly
    this here twice, and because it scans commit *ranges*, deleting the literal in a
    later commit does not clear it: the branch has to be squashed.

    The fix that holds is `tests/_secret_fixtures.py`, which concatenates the parts at
    import time — byte-identical input to the code under test, no literal in the tree.

    Two shapes are reported: an assignment whose *name* says credential, and a value
    whose *form* is a known credential regardless of name.
    """
    findings: list[Finding] = []

    for path in _walk(root, ".py"):
        if path.name == "repo_trust_guards.py":
            continue  # this file's own patterns are regexes, not credentials
        module = _parse(path)
        if module is None:
            continue
        docstrings = _docstring_constants(module)
        for node in ast.walk(module):
            # A known credential token anywhere inside an executable string constant.
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstrings and _SECRET_TOKEN.search(node.value):
                    findings.append(
                        Finding(
                            "committed-secret-literal",
                            _rel(path, root),
                            node.lineno,
                            "string literal contains a recognised credential token — "
                            "assemble it at runtime (see tests/_secret_fixtures.py)",
                        )
                    )
                continue

            # `api_key = "..."` / `secret: str = "..."` / `secret="..."`
            named: list[tuple[str, ast.expr]] = []
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        named.append((target.id, node.value))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    named.append((node.target.id, node.value))
            elif isinstance(node, ast.keyword) and node.arg:
                named.append((node.arg, node.value))

            for name, value in named:
                if not _SECRET_NAME.search(name):
                    continue
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    if _is_secretish_value(value.value):
                        findings.append(
                            Finding(
                                "committed-secret-literal",
                                _rel(path, root),
                                node.lineno,
                                f"`{name}` is assigned a literal value — assemble "
                                "credential-shaped fixtures at runtime",
                            )
                        )
    return findings


# ── guard 3: server web code must not fall back to demo identity ─────────────
#: The one module allowed to name the demo persona: it *is* the demo-mode adapter.
DEMO_IDENTITY_OWNER = Path("apps") / "web" / "lib" / "identity.ts"
_DEMO_LITERAL = re.compile(r"\b(?:tenant_demo|user_demo|DEMO_TENANT|DEMO_USER)\b")


def _strip_ts_comments(source: str) -> str:
    """Remove `//` and `/* */` comments so prose about the bug is not the bug.

    String-aware: a `//` inside a quoted string is not a comment. Deliberately small —
    it needs to be right about comments and strings, nothing else.
    """
    out: list[str] = []
    i, n = 0, len(source)
    quote: str | None = None
    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if quote:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(nxt)
                    i += 2
                    continue
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (source[i] == "*" and source[i + 1] == "/"):
                if source[i] == "\n":
                    out.append("\n")  # keep line numbers honest
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def check_no_demo_identity_in_server_code(root: Path = REPO) -> list[Finding]:
    """Server-executed web code must not name the demo tenant or user.

    The BFF exists so identity is attached on the *server* and cannot be chosen by
    the client. A hard-coded demo scope in that path defeats the point: it was
    previously possible for a demo session to mint a `tenant_admin` credential and
    share it, and separately for `lib/api.ts` to ship `DEMO_TENANT`/`DEMO_USER`
    constants that pinned every request to one shared persona.

    `lib/identity.ts` is the exception by construction — it is the module that
    *implements* demo mode and refuses to in production. Everything else on the server
    resolves identity through it.
    """
    findings: list[Finding] = []
    web = root / "apps" / "web"
    if not web.exists():
        return findings

    owner = root / DEMO_IDENTITY_OWNER
    server_trees = [web / "app" / "api", web / "lib"]

    for tree in server_trees:
        if not tree.exists():
            continue
        for path in list(_walk(tree, ".ts")) + list(_walk(tree, ".tsx")):
            if path == owner or "__tests__" in path.parts:
                continue
            code = _strip_ts_comments(path.read_text(encoding="utf-8", errors="ignore"))
            for lineno, line in enumerate(code.splitlines(), start=1):
                if _DEMO_LITERAL.search(line):
                    findings.append(
                        Finding(
                            "demo-identity-in-server-code",
                            _rel(path, root),
                            lineno,
                            "server code names the demo persona — resolve identity "
                            "through lib/identity.ts instead",
                        )
                    )
    return findings


# ── guard 4: retired infrastructure must not re-enter runtime code ───────────
#: module name -> why it was removed. Import means "something uses it again".
RETIRED_IMPORTS = {
    "redis": "declared, health-gated and paid for, but no code ever read it",
    "celery": "the lifecycle workers replaced it; never wired up",
}
#: Settings field names that were removed along with the dependency.
RETIRED_SETTINGS = {"redis_url": "Redis is not part of the topology"}


def check_no_retired_infrastructure(root: Path = REPO) -> list[Finding]:
    """A removed dependency must not creep back as configuration.

    Redis was in `Settings`, in Compose, health-gating both services' startup, and
    listed as a required Railway service — while no runtime code imported a client.
    A declared-but-unused dependency is a service to pay for, a health check that can
    fail a deploy, and an architecture diagram that misleads every reader.

    This is not a ban. If something genuinely starts using Redis, a real import will
    exist, this guard will fail, and the right response is to update it to assert the
    consumer rather than to allowlist the config.

    Import detection is AST-based, so `# we removed redis` and a docstring explaining
    the decision do not register.
    """
    findings: list[Finding] = []

    for tree_root in RUNTIME_TREES:
        base = root / tree_root
        if not base.exists():
            continue
        for path in _walk(base, ".py"):
            module = _parse(path)
            if module is None:
                continue
            for node in ast.walk(module):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module.split(".")[0]]
                for name in names:
                    if name in RETIRED_IMPORTS:
                        findings.append(
                            Finding(
                                "retired-infrastructure",
                                _rel(path, root),
                                node.lineno,
                                f"imports `{name}` — {RETIRED_IMPORTS[name]}; if it is "
                                "genuinely in use now, update this guard to assert that",
                            )
                        )

    config = root / "services" / "api" / "app" / "core" / "config.py"
    if config.exists():
        module = _parse(config)
        if module is not None:
            for node in ast.walk(module):
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    field = node.target.id
                    if field in RETIRED_SETTINGS:
                        findings.append(
                            Finding(
                                "retired-infrastructure",
                                _rel(config, root),
                                node.lineno,
                                f"`{field}` is back in Settings — {RETIRED_SETTINGS[field]}",
                            )
                        )
    return findings


GUARDS = {
    "sys-path-mutation": check_no_sys_path_mutation,
    "committed-secret-literal": check_no_committed_secret_literals,
    "demo-identity-in-server-code": check_no_demo_identity_in_server_code,
    "retired-infrastructure": check_no_retired_infrastructure,
}


def run_all(root: Path = REPO) -> list[Finding]:
    findings: list[Finding] = []
    for guard in GUARDS.values():
        findings.extend(guard(root))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--guard", choices=sorted(GUARDS), help="run a single guard")
    args = parser.parse_args()

    guards = {args.guard: GUARDS[args.guard]} if args.guard else GUARDS
    findings = [f for guard in guards.values() for f in guard(args.root)]

    if findings:
        print(f"✗ {len(findings)} structural guard finding(s):\n", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print(f"✓ {len(guards)} structural guard(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
