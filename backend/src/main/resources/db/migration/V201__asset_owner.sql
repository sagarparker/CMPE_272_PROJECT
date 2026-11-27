ALTER TABLE assets ADD CONSTRAINT assets_owner_fk FOREIGN KEY(owner_id) REFERENCES users(id);
CREATE INDEX assets_owner_created_idx ON assets(owner_id,created_at DESC);
CREATE INDEX assets_ready_idx ON assets(processing_status);
