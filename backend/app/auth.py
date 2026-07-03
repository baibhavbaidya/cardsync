"""Clerk JWT authentication dependency for FastAPI endpoints."""

import json
import os
import time

import httpx
import jwt as pyjwt
from fastapi import HTTPException, Header

CLERK_SECRET_KEY = os.environ["CLERK_SECRET_KEY"]
_JWKS_URL = "https://api.clerk.com/v1/jwks"

_jwks_keys: list = []
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 3600  # seconds before re-fetching public keys


async def _fetch_jwks() -> list:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            _JWKS_URL,
            headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()["keys"]


async def _get_public_key(kid: str):
    global _jwks_keys, _jwks_fetched_at

    if not _jwks_keys or (time.monotonic() - _jwks_fetched_at) > _JWKS_TTL:
        _jwks_keys = await _fetch_jwks()
        _jwks_fetched_at = time.monotonic()

    key_data = next((k for k in _jwks_keys if k["kid"] == kid), None)
    if key_data is None:
        # Rotate keys: force one refresh before giving up
        _jwks_keys = await _fetch_jwks()
        _jwks_fetched_at = time.monotonic()
        key_data = next((k for k in _jwks_keys if k["kid"] == kid), None)

    if key_data is None:
        raise HTTPException(status_code=401, detail="Unknown signing key")

    from jwt.algorithms import RSAAlgorithm  # requires PyJWT[cryptography]
    return RSAAlgorithm.from_jwk(json.dumps(key_data))


async def verify_token(token: str) -> str:
    """Verify a Clerk JWT and return the user_id (sub claim)."""
    try:
        header = pyjwt.get_unverified_header(token)
    except pyjwt.exceptions.DecodeError:
        raise HTTPException(status_code=401, detail="Malformed token")

    kid = header.get("kid")
    if not kid:
        raise HTTPException(status_code=401, detail="Token missing key ID")

    public_key = await _get_public_key(kid)

    try:
        payload = pyjwt.decode(token, public_key, algorithms=["RS256"])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing sub claim")
    return user_id


async def get_current_user(authorization: str = Header(...)) -> str:
    """FastAPI dependency: extracts Bearer token from Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must be Bearer token")
    return await verify_token(authorization[7:])
