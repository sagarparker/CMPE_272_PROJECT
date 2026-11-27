package com.mediamesh.media;

import java.time.LocalDate;
import java.util.UUID;

public record Asset(
        UUID id,
        UUID ownerId,
        String objectKey,
        MediaType mediaType,
        String title,
        String description,
        String species,
        String location,
        LocalDate capturedAt,
        String contributor,
        String usageNote,
        AssetStatus processingStatus
) {}
