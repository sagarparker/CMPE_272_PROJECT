package com.mediamesh.demo;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDate;
import java.util.*;
import org.springframework.stereotype.Component;

/**
 * The bundled, checksum-pinned showcase manifest (ml-service/evaluation/demo-manifest.json).
 * Selection order matches mediamesh_ml.dataset.select_images; asset IDs are stable UUIDv5 values
 * (also used by the retired command-line seed), so reruns recognise existing images.
 */
@Component
public class DemoManifest {
    public static final List<Integer> IMAGE_COUNTS = List.of(20, 50, 100, 500);
    private static final String RESOURCE = "/demo/demo-manifest.json";
    private static final UUID NAMESPACE_URL = UUID.fromString("6ba7b811-9dad-11d1-80b4-00c04fd430c8");
    private static final Set<String> HOSTS = Set.of("upload.wikimedia.org", "thumb.wikimedia.org");

    public record Item(String id, String filename, String title, String description, String species,
            String location, LocalDate capturedAt, String creator, String license, String licenseUrl,
            String sourcePage, String downloadUrl, String sha256, String domain, List<String> sha256Alternates) {
        public boolean acceptsSha256(String digest) {
            return sha256.equals(digest) || sha256Alternates.contains(digest);
        }
        public UUID assetId() {
            return uuid5(NAMESPACE_URL, "mediamesh:demo:" + id + ":" + sha256);
        }
        public String assetTitle() {
            String label = domain.isEmpty() ? domain
                    : domain.substring(0, 1).toUpperCase(Locale.ROOT) + domain.substring(1).toLowerCase(Locale.ROOT);
            String value = label + " | " + title;
            return value.length() > 255 ? value.substring(0, 255) : value;
        }
        public String usageNote() {
            return "%s. Credit: %s. Source: %s. License: %s.".formatted(license, creator, sourcePage,
                    licenseUrl == null || licenseUrl.isBlank() ? sourcePage : licenseUrl);
        }
    }

    private final ObjectMapper json;
    private volatile List<Item> ordered;

    public DemoManifest(ObjectMapper json) { this.json = json; }

    /** Stable, nested subsets spread round-robin across domains; images only. */
    public List<Item> select(int count) {
        if (!IMAGE_COUNTS.contains(count)) throw new IllegalArgumentException("Image count must be 20, 50, 100 or 500");
        List<Item> all = ordered();
        if (all.size() < count) throw new IllegalStateException("Manifest has only " + all.size() + " images");
        return all.subList(0, count);
    }

    private List<Item> ordered() {
        if (ordered == null) {
            synchronized (this) {
                if (ordered == null) ordered = load();
            }
        }
        return ordered;
    }

    private List<Item> load() {
        JsonNode items;
        try (InputStream in = DemoManifest.class.getResourceAsStream(RESOURCE)) {
            if (in == null) throw new IllegalStateException("Demo manifest is not bundled with the backend");
            items = json.readTree(in).path("items");
        } catch (IOException e) {
            throw new IllegalStateException("Demo manifest could not be read", e);
        }
        Map<String, List<Item>> groups = new LinkedHashMap<>();
        Set<String> ids = new HashSet<>();
        for (JsonNode node : items) {
            if (!ids.add(node.path("id").asText())) throw new IllegalStateException("Duplicate demo sample IDs");
            if (!"image".equals(text(node, "mediaType", "image"))) continue;
            Item item = item(node);
            groups.computeIfAbsent(item.domain(), key -> new ArrayList<>()).add(item);
        }
        List<Item> result = new ArrayList<>();
        int longest = groups.values().stream().mapToInt(List::size).max().orElse(0);
        for (int index = 0; index < longest; index++)
            for (List<Item> group : groups.values()) if (index < group.size()) result.add(group.get(index));
        return List.copyOf(result);
    }

    static Item item(JsonNode node) {
        String filename = text(node, "filename", "");
        if (filename.isEmpty() || filename.contains("/") || filename.contains("\\") || !filename.endsWith(".jpg"))
            throw new IllegalStateException("Invalid demo filename: " + filename);
        URI url = URI.create(text(node, "download_url", ""));
        if (!"https".equals(url.getScheme()) || !HOSTS.contains(url.getHost()))
            throw new IllegalStateException("Expected an approved Wikimedia HTTPS image URL");
        String sha = text(node, "sha256", "");
        if (!sha.matches("[0-9a-f]{64}")) throw new IllegalStateException("Manifest must pin SHA-256 values");
        List<String> alternates = new ArrayList<>();
        JsonNode alternatives = node.get("sha256_alternates");
        if (alternatives != null) {
            if (!alternatives.isArray()) throw new IllegalStateException("SHA-256 alternates must be an array");
            for (JsonNode alternative : alternatives) {
                if (!alternative.isTextual() || !alternative.asText().matches("[0-9a-f]{64}"))
                    throw new IllegalStateException("Manifest must pin valid alternate SHA-256 values");
                alternates.add(alternative.asText());
            }
        }
        String captured = text(node, "capturedAt", null);
        Item item = new Item(text(node, "id", ""), filename, text(node, "title", ""),
                text(node, "description", null), text(node, "species", null), text(node, "location", null),
                captured == null ? null : LocalDate.parse(captured), text(node, "creator", ""),
                text(node, "license", ""), text(node, "license_url", null), text(node, "source_page", ""),
                url.toString(), sha, text(node, "domain", ""), List.copyOf(alternates));
        if (item.creator().isBlank() || item.license().isBlank() || item.sourcePage().isBlank())
            throw new IllegalStateException("Missing credits: " + item.id());
        return item;
    }

    private static String text(JsonNode node, String field, String fallback) {
        JsonNode value = node.get(field);
        return value == null || value.isNull() ? fallback : value.asText();
    }

    static UUID uuid5(UUID namespace, String name) {
        try {
            MessageDigest sha1 = MessageDigest.getInstance("SHA-1");
            sha1.update(ByteBuffer.allocate(16).putLong(namespace.getMostSignificantBits())
                    .putLong(namespace.getLeastSignificantBits()).array());
            byte[] hash = sha1.digest(name.getBytes(StandardCharsets.UTF_8));
            hash[6] = (byte) ((hash[6] & 0x0f) | 0x50);
            hash[8] = (byte) ((hash[8] & 0x3f) | 0x80);
            ByteBuffer bytes = ByteBuffer.wrap(hash, 0, 16);
            return new UUID(bytes.getLong(), bytes.getLong());
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
