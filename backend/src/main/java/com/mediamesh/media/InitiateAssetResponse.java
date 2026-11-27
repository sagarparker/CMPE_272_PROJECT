package com.mediamesh.media;

import java.util.UUID;

public record InitiateAssetResponse(
        UUID assetId,
        String uploadUrl,
        AssetStatus status,
        java.util.Map<String, String> uploadHeaders
) {}
