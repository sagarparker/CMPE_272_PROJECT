package com.mediamesh.media;
import java.time.LocalDate;
import java.util.UUID;
public record AssetView(UUID assetId, UUID ownerId, MediaType mediaType, String title, String description,
        String species, String location, LocalDate capturedAt, String contributor, String usageNote,
        AssetStatus processingStatus) {
    public static AssetView of(Asset a) {
        return new AssetView(a.id(),a.ownerId(),a.mediaType(),a.title(),a.description(),a.species(),a.location(),
                a.capturedAt(),a.contributor(),a.usageNote(),a.processingStatus());
    }
}
