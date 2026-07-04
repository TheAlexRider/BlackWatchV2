-- Local username + password auth. Deliberately minimal: one users table
-- (username, hash), one sessions table (id, username, expiry). Sliding
-- 30-min TTL enforced in Python — DB just holds the state.
--
-- Hash format is `pbkdf2_sha256$<iters>$<b64-salt>$<b64-key>` produced by
-- blackwatch/auth.py using stdlib hashlib.pbkdf2_hmac, so this schema has
-- no dependency on bcrypt/argon2/etc.

CREATE TABLE IF NOT EXISTS auth_users (
    username        TEXT PRIMARY KEY,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id      TEXT PRIMARY KEY,
    username        TEXT NOT NULL REFERENCES auth_users(username) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS auth_sessions_username_idx
    ON auth_sessions(username);
CREATE INDEX IF NOT EXISTS auth_sessions_expires_idx
    ON auth_sessions(expires_at);
