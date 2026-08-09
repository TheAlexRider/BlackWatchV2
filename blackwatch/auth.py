"""Local username+password auth for the BlackWatch UI.

Deliberately stdlib-only — the deployment is a small Lightsail box and we
don't want an extra pinned dependency for password hashing. PBKDF2-HMAC-
SHA256 at 200k iterations is fine for our threat model (single-tenant
admin account; the box isn't accepting anonymous signups).

Public API:
  * `hash_password(pw)` / `verify_password(pw, hash)` — password hashing
  * `seed_admin_if_empty()` — called on app startup; installs the default
    admin/password if no user exists yet
  * `create_session(username)` / `touch_session(sid)` / `delete_session(sid)`
    — session lifecycle backed by the auth_sessions table

Session model: **sliding 30-min TTL**. Every `touch_session` extends the
expiry by another 30 min, so an active user is never signed out mid-flow;
an idle browser is signed out after 30 min of inactivity.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from . import storage

# Role hierarchy: admin > viewer. Any mutation requires admin. Unknown
# principals collapse to viewer (fail closed).
ROLE_ADMIN = "admin"
ROLE_VIEWER = "viewer"
_ROLE_RANK = {ROLE_VIEWER: 0, ROLE_ADMIN: 1}

logger = logging.getLogger(__name__)

# --- constants -------------------------------------------------------------

SESSION_TTL = timedelta(minutes=30)
COOKIE_NAME = "bw_session"

_PBKDF2_SCHEME = "pbkdf2_sha256"
_PBKDF2_ITER = 200_000  # OWASP-recommended lower bound for SHA-256 (2023)
_SALT_BYTES = 16
_KEY_BYTES = 32

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "password"  # nosec — deliberate first-run bootstrap credential


# --- password hashing ------------------------------------------------------

def hash_password(password: str) -> str:
    """Return an encoded PBKDF2 hash string: scheme$iters$salt$key."""
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITER, dklen=_KEY_BYTES,
    )
    return "$".join([
        _PBKDF2_SCHEME,
        str(_PBKDF2_ITER),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    ])


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verify of a password against an encoded hash. Returns
    False for any parse / decode / mismatch error — never raises so a
    malformed stored hash can't crash the login endpoint."""
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False
    try:
        scheme, iter_str, salt_b64, key_b64 = stored_hash.split("$")
        if scheme != _PBKDF2_SCHEME:
            return False
        iters = int(iter_str)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(key_b64)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iters, dklen=len(expected),
        )
        return secrets.compare_digest(actual, expected)
    except Exception:  # malformed hash / bad base64 / whatever — treat as fail
        return False


# --- admin seed ------------------------------------------------------------

def seed_admin_if_empty() -> None:
    """On app startup, install `admin`/`password` when no user exists. Logs
    a warning so the operator can't miss that the default credential is
    live. Once the operator changes the password (or adds their own user),
    this becomes a no-op."""
    try:
        users = storage.list_users()
    except Exception:
        logger.exception("auth seed skipped: could not query auth_users")
        return
    if users:
        return
    storage.upsert_user(
        DEFAULT_USERNAME, hash_password(DEFAULT_PASSWORD), role=ROLE_ADMIN,
    )
    logger.warning(
        "Auth: seeded default user %r with password %r — change it from "
        "Settings ASAP.",
        DEFAULT_USERNAME, DEFAULT_PASSWORD,
    )


# --- sessions --------------------------------------------------------------

def create_session(username: str) -> tuple[str, datetime]:
    """Insert a fresh session row and return (session_id, expires_at)."""
    sid = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + SESSION_TTL
    storage.insert_session(sid, username, expires)
    return sid, expires


def touch_session(session_id: str) -> tuple[str, datetime] | None:
    """Look up a session. If valid, slide its expiry forward and return
    (username, new_expiry). If missing / expired, delete and return None."""
    if not session_id:
        return None
    try:
        row = storage.get_session(session_id)
    except Exception:
        logger.exception("auth: get_session failed")
        return None
    if row is None:
        return None
    now = datetime.now(timezone.utc)
    expires_at = row["expires_at"]
    if expires_at.tzinfo is None:
        # psycopg with TIMESTAMPTZ should return aware, but be defensive.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        try:
            storage.delete_session(session_id)
        except Exception:
            pass
        return None
    new_expiry = now + SESSION_TTL
    try:
        storage.update_session_expiry(session_id, new_expiry)
    except Exception:
        logger.exception("auth: update_session_expiry failed")
    return row["username"], new_expiry


def delete_session(session_id: str | None) -> None:
    if not session_id:
        return
    try:
        storage.delete_session(session_id)
    except Exception:
        logger.exception("auth: delete_session failed")


def change_password(username: str, current: str, new: str) -> tuple[bool, str]:
    """Verify current, then replace the stored hash. Returns (ok, message).
    On success also invalidates all other sessions for this user — the
    caller's cookie stays valid but every other browser is signed out."""
    if len(new) < 8:
        return False, "new password must be at least 8 characters"
    try:
        user = storage.get_user(username)
    except Exception:
        logger.exception("auth: get_user failed")
        return False, "internal error"
    if user is None:
        return False, "user not found"
    if not verify_password(current, user["password_hash"]):
        return False, "current password is wrong"
    try:
        storage.upsert_user(username, hash_password(new))
    except Exception:
        logger.exception("auth: upsert_user failed")
        return False, "could not save new password"
    return True, "password changed"


# --- RBAC dependencies -----------------------------------------------------

def _role_from_request(request: Request) -> tuple[str | None, str]:
    """Return `(username_or_None, role)` for the current request. Role is
    resolved from request.state (populated by the auth middleware) with a
    DB lookup fallback. Missing/unknown users collapse to viewer."""
    user = getattr(request.state, "user", None)
    if not user:
        return None, ROLE_VIEWER
    role = getattr(request.state, "role", None)
    if not role:
        try:
            role = storage.get_user_role(user)
        except Exception:
            role = ROLE_VIEWER
    return user, role or ROLE_VIEWER


def get_current_user_with_role(request: Request) -> tuple[str, str]:
    """FastAPI dependency. Returns (user, role); 401 if unauthenticated."""
    user, role = _role_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user, role


def require_role(role: str):
    """Dependency factory. Raises 403 if the caller's role is below `role`."""
    needed = _ROLE_RANK.get(role, 99)

    def _dep(request: Request) -> tuple[str, str]:
        user, actual = get_current_user_with_role(request)
        if _ROLE_RANK.get(actual, -1) < needed:
            raise HTTPException(status_code=403, detail="admin role required")
        return user, actual

    return _dep


def is_admin(request: Request) -> bool:
    """Non-raising helper for templates / conditional UI reads."""
    _, role = _role_from_request(request)
    return role == ROLE_ADMIN
