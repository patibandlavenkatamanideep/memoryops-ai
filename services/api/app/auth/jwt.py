"""Dependency-free JWT verification (HS256/384/512).

MemoryOps does not ship an auth *product* — it verifies the identity an upstream
issuer already minted. HMAC verification needs only the stdlib, so the default path
adds no dependency and tests need no external keys. RS256/ES256 (asymmetric / JWKS)
is supported *iff* `cryptography` is installed; otherwise a clear error tells the
operator to install it. See `docs/auth-adapters.md`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

_HMAC_ALGS = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}


class JWTError(ValueError):
    """Raised when a token is malformed, has a bad signature, or is expired."""


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _verify_hmac(alg: str, signing_input: bytes, signature: bytes, secret: str) -> bool:
    digest = _HMAC_ALGS[alg]
    expected = hmac.new(secret.encode("utf-8"), signing_input, digest).digest()
    return hmac.compare_digest(expected, signature)


def _verify_rsa(alg: str, signing_input: bytes, signature: bytes, public_key: str) -> bool:
    try:  # optional: only needed for asymmetric algorithms
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.exceptions import InvalidSignature
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise JWTError(
            f"algorithm {alg} needs the 'cryptography' package; "
            "install it or use an HS* algorithm"
        ) from exc

    hash_alg = {"RS256": hashes.SHA256(), "RS384": hashes.SHA384(), "RS512": hashes.SHA512()}[alg]
    key = serialization.load_pem_public_key(public_key.encode("utf-8"))
    try:
        key.verify(signature, signing_input, padding.PKCS1v15(), hash_alg)
        return True
    except InvalidSignature:
        return False


def decode_jwt(
    token: str,
    *,
    key: str,
    algorithms: list[str],
    audience: str | None = None,
    issuer: str | None = None,
    leeway: int = 60,
    now: float | None = None,
) -> dict:
    """Verify signature + standard claims and return the payload.

    `key` is the shared secret (HS*) or PEM public key (RS*). Raises `JWTError` on
    any failure — a caller should treat that as 401, never as a server error.
    """
    if not token or token.count(".") != 2:
        raise JWTError("token is not a well-formed JWT")
    header_b64, payload_b64, sig_b64 = token.split(".")
    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(sig_b64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise JWTError("token segments are not valid base64url/JSON") from exc

    alg = header.get("alg")
    if alg not in algorithms:
        raise JWTError(f"algorithm '{alg}' is not in the allowed set {algorithms}")

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    if alg in _HMAC_ALGS:
        valid = _verify_hmac(alg, signing_input, signature, key)
    elif alg in ("RS256", "RS384", "RS512"):
        valid = _verify_rsa(alg, signing_input, signature, key)
    else:
        raise JWTError(f"unsupported algorithm '{alg}'")
    if not valid:
        raise JWTError("signature verification failed")

    now = time.time() if now is None else now
    exp = payload.get("exp")
    if exp is not None and now > float(exp) + leeway:
        raise JWTError("token has expired")
    nbf = payload.get("nbf")
    if nbf is not None and now < float(nbf) - leeway:
        raise JWTError("token is not yet valid (nbf)")
    if audience is not None:
        aud = payload.get("aud")
        aud_set = set(aud) if isinstance(aud, list) else {aud}
        if audience not in aud_set:
            raise JWTError("token audience mismatch")
    if issuer is not None and payload.get("iss") != issuer:
        raise JWTError("token issuer mismatch")
    return payload


def claim_path(payload: dict, dotted: str) -> str | None:
    """Read a possibly nested claim (e.g. `app_metadata.tenant_id`)."""
    node: object = payload
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return str(node) if node is not None and not isinstance(node, (dict, list)) else None
