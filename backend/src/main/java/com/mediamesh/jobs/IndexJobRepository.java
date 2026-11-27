package com.mediamesh.jobs;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.UUID;

@Repository
public class IndexJobRepository {
    private final JdbcTemplate jdbc;

    public IndexJobRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public boolean insertIfAbsent(UUID assetId, String objectKey, String mediaType) {
        return jdbc.update("""
                INSERT INTO index_jobs(id, asset_id, media_reference, media_type)
                VALUES (?, ?, ?, ?)
                ON CONFLICT DO NOTHING
                """, UUID.randomUUID(), assetId, objectKey, mediaType) == 1;
    }

}
