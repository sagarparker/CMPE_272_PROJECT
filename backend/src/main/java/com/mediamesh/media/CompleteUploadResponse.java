package com.mediamesh.media;

import java.util.UUID;

public record CompleteUploadResponse(
        UUID assetId,
        AssetStatus status
) {}
