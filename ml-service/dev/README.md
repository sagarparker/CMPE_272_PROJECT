# Local database prerequisites

Teammate 2's production `assets` schema is not implemented in this checkout.
`bootstrap_assets.sql` is a **test/local fixture only**, not a V2xx migration.
It creates a minimal `assets(id UUID)` only in the isolated development or test
database. It must never be applied to a production/shared database. The vector
migration assumes UUID asset IDs; confirm that contract before integration.

Apply fixture/migrations explicitly through the migration tool added in step 3.
Do not attach these files to PostgreSQL's automatic init directory; migration
history and existing data must survive container restarts.
