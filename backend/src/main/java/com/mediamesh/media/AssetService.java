package com.mediamesh.media;

import com.mediamesh.jobs.IndexJobRepository;
import com.mediamesh.storage.MediaStorage;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.nio.file.InvalidPathException;
import java.nio.file.Paths;
import java.util.UUID;

@Service
public class AssetService {
    private final AssetRepository assets;
    private final IndexJobRepository jobs;
    private final MediaStorage storage;

    public AssetService(AssetRepository assets, IndexJobRepository jobs, MediaStorage storage) {
        this.assets = assets;
        this.jobs = jobs;
        this.storage = storage;
    }

    @Transactional
    public InitiateAssetResponse initiate(InitiateAssetRequest request, UUID ownerId) {
        MediaType mediaType = validatedMediaType(request);
        UUID assetId = UUID.randomUUID();
        String filename = safeFilename(request.filename());
        String objectKey = "assets/%s/%s/source/%s"
                .formatted(ownerId, assetId, filename);

        Asset asset = new Asset(
                assetId, ownerId, objectKey, mediaType, request.title(),
                request.description(), request.species(), request.location(),
                request.capturedAt(), request.contributor(), request.usageNote(),
                AssetStatus.UPLOADING);
        assets.insert(asset);

        return new InitiateAssetResponse(
                assetId,
                storage.createUploadUrl(objectKey, request.contentType()),
                AssetStatus.UPLOADING, storage.uploadHeaders());
    }

    @Transactional
    public CompleteUploadResponse complete(UUID assetId, UUID requesterId) {
        Asset asset = assets.findByIdForUpdate(assetId).orElseThrow(() ->
                new ResponseStatusException(HttpStatus.NOT_FOUND, "Asset not found"));
        if (!asset.ownerId().equals(requesterId)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Asset is owned by another user");
        }
        if (asset.processingStatus() == AssetStatus.PROCESSING
                || asset.processingStatus() == AssetStatus.READY) {
            return new CompleteUploadResponse(assetId, asset.processingStatus());
        }

        if (asset.processingStatus() != AssetStatus.UPLOADING) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Asset cannot be completed in its current state");
        }
        storage.verifyUpload(asset.objectKey(), asset.mediaType().name());
        if (!assets.markProcessing(assetId)
                || !jobs.insertIfAbsent(assetId, asset.objectKey(), asset.mediaType().name())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Asset state changed");
        }

        return new CompleteUploadResponse(assetId, AssetStatus.PROCESSING);
    }

    private String safeFilename(String filename) {
        String name;
        try {
            name = Paths.get(filename).getFileName().toString();
        } catch (InvalidPathException | NullPointerException e) {
            name = "media";
        }
        name = name.replaceAll("[^A-Za-z0-9._-]", "_");
        return name.isBlank() ? "media" : name;
    }

    private MediaType validatedMediaType(InitiateAssetRequest request) {
        MediaType inferred = switch (request.contentType()) {
            case "image/jpeg", "image/png" -> MediaType.image;
            case "video/mp4", "video/quicktime" -> MediaType.video;
            default -> throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Unsupported media content type");
        };
        if (request.mediaType() != null && request.mediaType() != inferred) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "Media type does not match content type");
        }
        return inferred;
    }
}
