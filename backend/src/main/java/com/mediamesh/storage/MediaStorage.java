package com.mediamesh.storage;

public interface MediaStorage {
    default java.util.Map<String, String> uploadHeaders() { return java.util.Map.of(); }
    String createUploadUrl(String objectKey, String contentType);

    String createAccessUrl(String objectKey, boolean download);

    void verifyUpload(String objectKey, String mediaType);

    /** Server-side write, used only by the administrator demo seed; replaces an existing object. */
    default void store(String objectKey, String contentType, byte[] content) {
        throw new UnsupportedOperationException("Server-side storage writes are not supported");
    }
}
