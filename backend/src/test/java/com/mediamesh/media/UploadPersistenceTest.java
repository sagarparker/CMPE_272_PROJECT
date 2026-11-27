package com.mediamesh.media;

import com.mediamesh.jobs.IndexJobRepository;
import com.mediamesh.storage.MediaStorage;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.jdbc.AutoConfigureTestDatabase;
import org.springframework.boot.test.autoconfigure.jdbc.JdbcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@JdbcTest(properties = "spring.flyway.enabled=false")
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import({AssetRepository.class, IndexJobRepository.class, AssetService.class})
@Transactional(propagation = Propagation.NOT_SUPPORTED)
@Testcontainers
class UploadPersistenceTest {
    @Container
    static final PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16-alpine");

    @DynamicPropertySource
    static void database(DynamicPropertyRegistry properties) {
        properties.add("spring.datasource.url", postgres::getJdbcUrl);
        properties.add("spring.datasource.username", postgres::getUsername);
        properties.add("spring.datasource.password", postgres::getPassword);
    }

    @Autowired JdbcTemplate jdbc;
    @Autowired AssetRepository assets;
    @Autowired AssetService service;
    @MockBean MediaStorage storage;
    private UUID owner;
    private UUID id;

    @BeforeEach
    void prepare() throws Exception {
        jdbc.execute("DROP TABLE IF EXISTS index_jobs, assets CASCADE");
        try (var source = getClass().getResourceAsStream(
                "/db/migration/V200__create_media_catalog.sql")) {
            jdbc.execute(new String(source.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8));
        }
        owner = UUID.randomUUID();
        id = UUID.randomUUID();
        assets.insert(new Asset(id, owner, "assets/photo.jpg", MediaType.image, "Photo",
                null, null, null, null, null, null, AssetStatus.UPLOADING));
    }

    @Test
    void repeatedAndConcurrentCompletionCreateOneJob() throws Exception {
        var executor = Executors.newFixedThreadPool(2);
        try {
            Callable<CompleteUploadResponse> complete = () -> service.complete(id, owner);
            var results = executor.invokeAll(List.of(complete, complete));
            for (var result : results) {
                assertThat(result.get().status()).isEqualTo(AssetStatus.PROCESSING);
            }
            assertThat(service.complete(id, owner).status()).isEqualTo(AssetStatus.PROCESSING);
            assertThat(jdbc.queryForObject("SELECT count(*) FROM index_jobs", Integer.class)).isEqualTo(1);
            verify(storage, times(1)).verifyUpload("assets/photo.jpg", "image");
        } finally {
            executor.shutdownNow();
        }
    }

    @Test
    void jobInsertFailureRollsBackAssetTransition() {
        jdbc.execute("ALTER TABLE index_jobs ADD CONSTRAINT reject_job CHECK (false)");
        assertThatThrownBy(() -> service.complete(id, owner)).isInstanceOf(RuntimeException.class);
        assertThat(state()).isEqualTo("UPLOADING");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM index_jobs", Integer.class)).isZero();
    }

    @Test
    void failedAssetIsNotReportedAsProcessing() {
        jdbc.update("UPDATE assets SET processing_status='FAILED' WHERE id=?", id);
        assertThatThrownBy(() -> service.complete(id, owner))
                .isInstanceOf(org.springframework.web.server.ResponseStatusException.class);
        assertThat(state()).isEqualTo("FAILED");
        verifyNoInteractions(storage);
    }

    @Test
    void rejectedUploadLeavesNoJob() {
        doThrow(new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.BAD_REQUEST, "Invalid upload"))
                .when(storage).verifyUpload("assets/photo.jpg", "image");
        assertThatThrownBy(() -> service.complete(id, owner)).isInstanceOf(RuntimeException.class);
        assertThat(state()).isEqualTo("UPLOADING");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM index_jobs", Integer.class)).isZero();
    }

    private String state() {
        return jdbc.queryForObject("SELECT processing_status FROM assets WHERE id=?", String.class, id);
    }
}
