-- Existing username/password administrators must not retain administrator access.
DELETE FROM user_roles WHERE role='ADMIN';
ALTER TABLE users ADD COLUMN primary_admin BOOLEAN NOT NULL DEFAULT false;
CREATE UNIQUE INDEX one_primary_admin ON users(primary_admin) WHERE primary_admin;
CREATE TABLE access_requests (
 id UUID PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id),
 status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 reviewed_by UUID REFERENCES users(id),
 reviewed_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX one_pending_access_request ON access_requests(user_id) WHERE status='PENDING';
CREATE TABLE access_request_roles (
 request_id UUID REFERENCES access_requests(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK (role IN ('UPLOADER','RESEARCHER')),
 PRIMARY KEY(request_id,role)
);
