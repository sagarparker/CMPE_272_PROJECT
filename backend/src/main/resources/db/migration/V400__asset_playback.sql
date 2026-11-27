-- Browser-safe H.264 MP4 written by the ML worker for videos. NULL until published;
-- previews then fall back to the original upload, and downloads always use it.
ALTER TABLE assets ADD COLUMN playback_key TEXT UNIQUE
    CHECK (playback_key IS NULL OR (media_type = 'video' AND playback_key LIKE 'assets/%'));
