package com.mediamesh.demo;

import com.mediamesh.identity.IdentityService;
import com.mediamesh.jobs.IndexJobRepository;
import com.mediamesh.media.AssetRepository;
import com.mediamesh.storage.MediaStorage;
import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.security.MessageDigest;
import java.sql.Array;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;

/**
 * Loads the bundled showcase images into whichever storage this backend uses (Azurite locally,
 * Azure Blob in deployment) and queues the normal indexing jobs. One run at a time; reruns resume.
 */
@Service
public class DemoSeedService {
    private static final Logger log = LoggerFactory.getLogger(DemoSeedService.class);
    private static final String USER_AGENT = "MediaMesh/0.1 (CMPE272 educational demo seed)";
    private static final int MAX_DOWNLOAD_BYTES = 20_000_000;

    public record Run(int images, String state, int processed, String error, Instant startedAt, Instant finishedAt) {}
    public record Status(int images, List<Integer> options, int ready, int processing, int uploading,
            int failed, int missing, Run run) {}

    private final DemoManifest manifest;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final AssetRepository assets;
    private final IndexJobRepository jobs;
    private final MediaStorage storage;
    private final IdentityService identities;
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10))
            .followRedirects(HttpClient.Redirect.NORMAL).build();
    private final ExecutorService worker = Executors.newSingleThreadExecutor(task -> {
        Thread thread = new Thread(task, "demo-seed");
        thread.setDaemon(true);
        return thread;
    });
    private volatile Run run;

    public DemoSeedService(DemoManifest manifest, JdbcTemplate jdbc, TransactionTemplate tx, AssetRepository assets,
            IndexJobRepository jobs, MediaStorage storage, IdentityService identities) {
        this.manifest = manifest;
        this.jdbc = jdbc;
        this.tx = tx;
        this.assets = assets;
        this.jobs = jobs;
        this.storage = storage;
        this.identities = identities;
    }

    public synchronized Status start(UUID owner, int images) {
        List<DemoManifest.Item> items = select(images);
        if (run != null && "RUNNING".equals(run.state()))
            throw new ResponseStatusException(HttpStatus.CONFLICT, "A seed run is already in progress");
        run = new Run(images, "RUNNING", 0, null, Instant.now(), null);
        identities.audit(owner, "DEMO_SEED", "demo-manifest", images + " images");
        worker.submit(() -> execute(owner, items));
        return status(images);
    }

    public Status status(int images) {
        List<DemoManifest.Item> items = select(images);
        Map<String, Integer> counts = counts(items);
        int found = counts.values().stream().mapToInt(Integer::intValue).sum();
        return new Status(images, DemoManifest.IMAGE_COUNTS, counts.getOrDefault("READY", 0),
                counts.getOrDefault("PROCESSING", 0), counts.getOrDefault("UPLOADING", 0),
                counts.getOrDefault("FAILED", 0), items.size() - found, run);
    }

    @PreDestroy
    void stop() { worker.shutdownNow(); }

    private List<DemoManifest.Item> select(int images) {
        try {
            return manifest.select(images);
        } catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, e.getMessage());
        }
    }

    private void execute(UUID owner, List<DemoManifest.Item> items) {
        int processed = 0;
        try {
            for (DemoManifest.Item item : items) {
                if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
                seed(owner, item);
                processed++;
                update(processed, "RUNNING", null);
            }
            update(processed, "COMPLETED", null);
            log.info("Demo seed stored {} images", processed);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            update(processed, "FAILED", "The seed run was interrupted; start it again to resume.");
        } catch (Exception e) {
            log.warn("Demo seed stopped after {} images", processed, e);
            String message = e instanceof SeedException ? e.getMessage()
                    : "Seeding stopped unexpectedly; start it again to resume. Check backend logs for details.";
            update(processed, "FAILED", message);
        }
    }

    private synchronized void update(int processed, String state, String error) {
        Run current = run;
        run = new Run(current.images(), state, processed, error, current.startedAt(),
                "RUNNING".equals(state) ? null : Instant.now());
    }

    private void seed(UUID owner, DemoManifest.Item item) throws IOException, InterruptedException {
        Existing existing = existing(owner, item);
        // Already stored and queued (or finished/failed): leave it to the normal worker.
        if (existing != null && !"UPLOADING".equals(existing.status())) return;
        byte[] content = download(item);
        UUID assetId = item.assetId();
        String key = "assets/%s/%s/source/%s".formatted(owner, assetId, item.filename());
        if (existing == null) {
            jdbc.update("""
                INSERT INTO assets(id,owner_id,s3_key,media_type,title,description,species,location,captured_at,
                                   contributor,usage_note,processing_status)
                VALUES (?,?,?,'image',?,?,?,?,?,?,?,'UPLOADING') ON CONFLICT (id) DO NOTHING
                """, assetId, owner, key, item.assetTitle(),
                    item.description() == null || item.description().isBlank() ? item.title() : item.description(),
                    item.species(), item.location(), item.capturedAt(), item.creator(), item.usageNote());
            existing = existing(owner, item);
            if (existing == null) throw new SeedException("Could not create the catalog entry for " + item.id());
            if (!"UPLOADING".equals(existing.status())) return;
        }
        // Only this seed writes UPLOADING demo objects, so replacing an interrupted upload is safe.
        storage.store(existing.key(), "image/jpeg", content);
        UUID id = existing.id();
        String objectKey = existing.key();
        tx.executeWithoutResult(status -> {
            if (assets.markProcessing(id)) jobs.insertIfAbsent(id, objectKey, "image");
        });
    }

    private record Existing(UUID id, String key, String status) {}

    private Existing existing(UUID owner, DemoManifest.Item item) {
        // Also recognise images added by earlier browser-based seeds for this owner.
        return jdbc.query("""
            SELECT id,s3_key,processing_status FROM assets WHERE id=? OR
              (owner_id=? AND title=? AND position(? in coalesce(usage_note,''))>0)
            ORDER BY created_at LIMIT 1
            """, (rs, n) -> new Existing(rs.getObject(1, UUID.class), rs.getString(2), rs.getString(3)),
                item.assetId(), owner, item.assetTitle(), item.sourcePage()).stream().findFirst().orElse(null);
    }

    private byte[] download(DemoManifest.Item item) throws IOException, InterruptedException {
        HttpRequest request = HttpRequest.newBuilder(URI.create(item.downloadUrl()))
                .timeout(Duration.ofSeconds(45)).header("User-Agent", USER_AGENT).GET().build();
        IOException last = null;
        for (int attempt = 0; attempt < 3; attempt++) {
            if (attempt > 0) Thread.sleep(5000L * attempt);
            try {
                HttpResponse<InputStream> response = http.send(request, HttpResponse.BodyHandlers.ofInputStream());
                byte[] content;
                try (InputStream body = response.body()) {
                    if (response.statusCode() != 200) {
                        last = new IOException("HTTP " + response.statusCode());
                        continue;
                    }
                    content = body.readNBytes(MAX_DOWNLOAD_BYTES + 1);
                }
                if (content.length > MAX_DOWNLOAD_BYTES)
                    throw new SeedException("Image " + item.id() + " exceeds the 20 MB download limit");
                if (!sha256(content).equals(item.sha256()))
                    throw new SeedException("Checksum mismatch for " + item.id() + "; the source file changed");
                return content;
            } catch (IOException e) {
                last = e;
            }
        }
        log.warn("Demo image download failed for {}", item.id(), last);
        throw new SeedException("Could not download " + item.id() + " from Wikimedia; start again to retry");
    }

    private Map<String, Integer> counts(List<DemoManifest.Item> items) {
        UUID[] ids = items.stream().map(DemoManifest.Item::assetId).toArray(UUID[]::new);
        String[] titles = items.stream().map(DemoManifest.Item::assetTitle).toArray(String[]::new);
        String[] sources = items.stream().map(DemoManifest.Item::sourcePage).toArray(String[]::new);
        return jdbc.execute((ConnectionCallback<Map<String, Integer>>) connection -> {
            Array idArray = connection.createArrayOf("uuid", ids);
            Array titleArray = connection.createArrayOf("text", titles);
            Array sourceArray = connection.createArrayOf("text", sources);
            try (var statement = connection.prepareStatement("""
                    SELECT a.processing_status, count(*)
                    FROM unnest(?::uuid[], ?::text[], ?::text[]) AS s(id,title,source)
                    JOIN LATERAL (SELECT processing_status FROM assets a
                        WHERE a.id=s.id OR (a.title=s.title AND position(s.source in coalesce(a.usage_note,''))>0)
                        ORDER BY a.created_at LIMIT 1) a ON true
                    GROUP BY a.processing_status
                    """)) {
                statement.setArray(1, idArray);
                statement.setArray(2, titleArray);
                statement.setArray(3, sourceArray);
                Map<String, Integer> result = new HashMap<>();
                try (var rows = statement.executeQuery()) {
                    while (rows.next()) result.put(rows.getString(1), rows.getInt(2));
                }
                return result;
            } finally {
                idArray.free();
                titleArray.free();
                sourceArray.free();
            }
        });
    }

    private static String sha256(byte[] content) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content));
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /** A failure whose message is safe and useful to show to the administrator. */
    static final class SeedException extends RuntimeException {
        SeedException(String message) { super(message); }
    }
}
