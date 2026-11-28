package com.mediamesh.demo;

import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

class DemoManifestTest {
    private final ObjectMapper json = new ObjectMapper();
    private static final String CANONICAL = "a".repeat(64);
    private static final String ALTERNATE = "b".repeat(64);

    private com.fasterxml.jackson.databind.node.ObjectNode sample() {
        var node = json.createObjectNode();
        node.put("id", "test-image");
        node.put("filename", "test.jpg");
        node.put("sha256", CANONICAL);
        node.put("download_url", "https://thumb.wikimedia.org/test.jpg");
        node.put("creator", "Contributor");
        node.put("license", "CC BY-SA 4.0");
        node.put("source_page", "https://commons.wikimedia.org/wiki/File:Test.jpg");
        return node;
    }

    @Test void acceptsOnlyExplicitlyPinnedVariantsAndPreservesAssetIdentity() {
        var node = sample();
        var original = DemoManifest.item(node);
        node.putArray("sha256_alternates").add(ALTERNATE);
        var updated = DemoManifest.item(node);
        assertTrue(updated.acceptsSha256(CANONICAL));
        assertTrue(updated.acceptsSha256(ALTERNATE));
        assertFalse(original.acceptsSha256(ALTERNATE));
        assertFalse(updated.acceptsSha256("c".repeat(64)));
        assertEquals(original.assetId(), updated.assetId());
    }

    @Test void rejectsInvalidAlternatePins() {
        var node = sample();
        node.putArray("sha256_alternates").add("not-a-hash");
        assertThrows(IllegalStateException.class, () -> DemoManifest.item(node));
        node.put("sha256_alternates", ALTERNATE);
        assertThrows(IllegalStateException.class, () -> DemoManifest.item(node));
    }

    @Test void bundledTwentyImageCollectionIncludesTheObservedRegionalVariants() {
        var items = new DemoManifest(json).select(20);
        assertEquals(20, items.size());
        assertEquals(3, items.stream().filter(i -> !i.sha256Alternates().isEmpty()).count());
        var bird = items.stream().filter(i -> i.id().equals("demo-bird-02")).findFirst().orElseThrow();
        assertTrue(bird.acceptsSha256("7fe3612f34ad8cd906b57e0025803e18513c859b4d41995a84fab80d2f621a06"));
    }
}
