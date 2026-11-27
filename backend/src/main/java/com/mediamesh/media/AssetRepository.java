package com.mediamesh.media;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

@Repository
public class AssetRepository {
    private final JdbcTemplate jdbc;

    public AssetRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void insert(Asset asset) {
        jdbc.update("""
                INSERT INTO assets(id, owner_id, s3_key, media_type, title, description,
                                  species, location, captured_at, contributor, usage_note,
                                  processing_status)
                VALUES (?, ?, ?, ?::text, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                asset.id(), asset.ownerId(), asset.objectKey(), asset.mediaType().name(),
                asset.title(), asset.description(), asset.species(), asset.location(),
                asset.capturedAt(), asset.contributor(), asset.usageNote(),
                asset.processingStatus().name());
    }

    private static final org.springframework.jdbc.core.RowMapper<Asset> MAPPER = (rs, n) -> new Asset(
            rs.getObject("id", UUID.class), rs.getObject("owner_id", UUID.class), rs.getString("s3_key"),
            MediaType.valueOf(rs.getString("media_type")), rs.getString("title"), rs.getString("description"),
            rs.getString("species"), rs.getString("location"), rs.getObject("captured_at", java.time.LocalDate.class),
            rs.getString("contributor"), rs.getString("usage_note"), AssetStatus.valueOf(rs.getString("processing_status")));

    public Optional<Asset> findByIdForUpdate(UUID id) {
        return jdbc.query("SELECT * FROM assets WHERE id=? FOR UPDATE", MAPPER, id).stream().findFirst();
    }
    /** Browser-safe MP4 published by the ML worker for a video, if any. */
    public Optional<String> playbackKey(UUID id) {
        return jdbc.queryForList("SELECT playback_key FROM assets WHERE id=? AND playback_key IS NOT NULL",
                String.class, id).stream().findFirst();
    }
    public Optional<Asset> findById(UUID id) {
        return jdbc.query("SELECT * FROM assets WHERE id=?", MAPPER, id).stream().findFirst();
    }
    public java.util.List<Asset> owned(UUID owner, int offset) {
        return jdbc.query("SELECT * FROM assets WHERE owner_id=? ORDER BY created_at DESC,id LIMIT 50 OFFSET ?", MAPPER,owner,offset);
    }
    public java.util.List<UUID> eligible(SearchRequest request) {
        return jdbc.queryForList("""
            SELECT id FROM assets WHERE processing_status='READY'
              AND (?::text IS NULL OR media_type=?)
              AND (?::text IS NULL OR position(lower(?) in lower(coalesce(species,'')))>0)
              AND (?::text IS NULL OR position(lower(?) in lower(coalesce(location,'')))>0)
              AND (?::date IS NULL OR captured_at>=?::date)
            """, UUID.class,
            request.mediaType()==null ? null : request.mediaType().name(), request.mediaType()==null ? null : request.mediaType().name(), request.species(),request.species(),
            request.location(),request.location(),request.capturedAfter(),request.capturedAfter());
    }
    public void update(UUID id, MetadataRequest body) {
        jdbc.update("""
            UPDATE assets SET title=?,description=?,species=?,location=?,captured_at=?,contributor=?,usage_note=?,
              updated_at=clock_timestamp() WHERE id=?
            """,body.title(),body.description(),body.species(),body.location(),body.capturedAt(),body.contributor(),body.usageNote(),id);
    }

    public boolean markProcessing(UUID id) {
        return jdbc.update("""
                UPDATE assets
                SET processing_status = 'PROCESSING', updated_at = clock_timestamp()
                WHERE id = ? AND processing_status = 'UPLOADING'
                """, id) == 1;
    }
}
