package com.mediamesh.storage;

public interface MediaStorage {
    default java.util.Map<String, String> uploadHeaders() { return java.util.Map.of(); }
    String createUploadUrl(String objectKey, String contentType);

    String createAccessUrl(String objectKey, boolean download);

    void verifyUpload(String objectKey, String mediaType);
}
