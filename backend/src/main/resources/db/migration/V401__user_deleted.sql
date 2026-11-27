-- Deleted accounts keep their row so audit history and media ownership stay intact.
-- Their Keycloak login, roles and API sessions are removed when deleted_at is set.
ALTER TABLE users ADD COLUMN deleted_at TIMESTAMPTZ;
