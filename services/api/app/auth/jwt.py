"""JWT verification via PyJWT, with optional JWKS.

MemoryOps does not ship an auth *product* — it verifies an identity an upstream
issuer already minted. We delegate the token crypto to **PyJWT** rather than
hand-rolling signature/again parsing (JWTs have a long history of subtle parser CVEs;
"dependency-free" buys nothing here). HS* works with PyJWT alone; RS*/ES* and JWKS
additionally need the `cryptography` package (`pip install "pyjwt[crypto]"`).

PyJWT is imported lazily so the app stays importable when auth is off (the default);
callers get a clear ``JWTError`` if the token can't be verified. The public
``decode_jwt`` signature and the ``JWTError`` wrapper are unchanged, so existing
callers/tests keep working.
"""

from __future__ import annotations


class JWTError(ValueError):
    """Raised when a token is malformed, has a bad signature, or is expired."""


# Cache one PyJWKClient per JWKS URL — it fetches + caches the issuer's signing keys.
_JWKS_CLIENTS: dict[str, object] = {}


def _require_pyjwt():
    try:
        import jwt as pyjwt
    except ImportError as exc:  # pragma: no cover — PyJWT ships in requirements
        raise JWTError(
            "JWT verification needs the 'PyJWT' package; install it "
            "(or 'pyjwt[crypto]' for RS*/ES*/JWKS)"
        ) from exc
    return pyjwt


def _jwks_signing_key(token: str, jwks_url: str):
    _require_pyjwt()
    try:
        from jwt import PyJWKClient
    except ImportError as exc:  # pragma: no cover
        raise JWTError("JWKS needs 'pyjwt[crypto]' (cryptography)") from exc
    client = _JWKS_CLIENTS.get(jwks_url)
    if client is None:
        client = PyJWKClient(jwks_url, cache_keys=True)
        _JWKS_CLIENTS[jwks_url] = client
    try:
        return client.get_signing_key_from_jwt(token).key
    except Exception as exc:  # noqa: BLE001 — surface any JWKS failure as JWTError
        raise JWTError(f"could not resolve JWKS signing key: {exc}") from exc


def decode_jwt(
    token: str,
    *,
    key: str = "",
    algorithms: list[str],
    audience: str | None = None,
    issuer: str | None = None,
    leeway: int = 60,
    now: float | None = None,  # kept for signature compatibility; PyJWT uses the clock
    jwks_url: str | None = None,
) -> dict:
    """Verify signature + standard claims and return the payload.

    `key` is the shared secret (HS*) or PEM public key (RS*/ES*). When `jwks_url` is
    given, the signing key is resolved from the issuer's JWKS instead. Raises
    `JWTError` on any failure — a caller should treat that as 401, never as a 500.
    """
    if not token or token.count(".") != 2:
        raise JWTError("token is not a well-formed JWT")

    pyjwt = _require_pyjwt()
    signing_key = _jwks_signing_key(token, jwks_url) if jwks_url else key
    try:
        return pyjwt.decode(
            token,
            signing_key,
            algorithms=list(algorithms),
            audience=audience,
            issuer=issuer,
            leeway=leeway,
            # Match the previous behavior: only check aud/iss when the caller asks.
            options={"verify_aud": audience is not None, "verify_iss": issuer is not None},
        )
    except pyjwt.PyJWTError as exc:
        raise JWTError(str(exc)) from exc


def claim_path(payload: dict, dotted: str) -> str | None:
    """Read a possibly nested claim (e.g. `app_metadata.tenant_id`)."""
    node: object = payload
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if node is None or isinstance(node, dict | list):
        return None
    return str(node)
