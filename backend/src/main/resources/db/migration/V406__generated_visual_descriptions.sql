ALTER TABLE assets ADD COLUMN generated_description text;
ALTER TABLE assets ADD COLUMN description_model text;
ALTER TABLE assets ADD COLUMN description_generated_at timestamptz;
