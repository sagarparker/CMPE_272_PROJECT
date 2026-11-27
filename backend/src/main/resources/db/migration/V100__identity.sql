CREATE TABLE users (
 id UUID PRIMARY KEY,
 issuer TEXT NOT NULL,
 subject TEXT NOT NULL,
 email TEXT NOT NULL,
 display_name TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 UNIQUE(issuer, subject)
);
CREATE TABLE user_roles (
 user_id UUID REFERENCES users(id) ON DELETE CASCADE,
 role TEXT CHECK (role IN ('ADMIN','UPLOADER','RESEARCHER')),
 PRIMARY KEY(user_id, role)
);
CREATE TABLE audit_events (
 id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor_id UUID NOT NULL REFERENCES users(id),
 action TEXT NOT NULL,
 target TEXT NOT NULL,
 detail TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE api_sessions (
 session_id TEXT PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id),
 started_at TIMESTAMPTZ NOT NULL,
 last_seen TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 revoked BOOLEAN NOT NULL DEFAULT false
);
