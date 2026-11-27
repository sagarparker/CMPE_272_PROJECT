package com.mediamesh.media;

import com.mediamesh.jobs.IndexJobRepository;
import com.mediamesh.storage.MediaStorage;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;

import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AssetServiceTest {
    @Test
    void completeCreatesProcessingJob() {
        AssetRepository assets = mock(AssetRepository.class);
        IndexJobRepository jobs = mock(IndexJobRepository.class);
        MediaStorage storage = mock(MediaStorage.class);
        UUID owner = UUID.randomUUID();
        UUID assetId = UUID.randomUUID();
        Asset asset = new Asset(assetId, owner, "assets/media/file.jpg",
                MediaType.image, "Elephant", null, null, null, null, null, null,
                AssetStatus.UPLOADING);

        when(assets.findByIdForUpdate(assetId)).thenReturn(Optional.of(asset));
        when(assets.markProcessing(assetId)).thenReturn(true);
        when(jobs.insertIfAbsent(assetId, asset.objectKey(), "image")).thenReturn(true);

        AssetService service = new AssetService(assets, jobs, storage);
        CompleteUploadResponse result = service.complete(assetId, owner);

        assertThat(result.status()).isEqualTo(AssetStatus.PROCESSING);
        verify(jobs).insertIfAbsent(assetId, asset.objectKey(), "image");
    }

    @Test
    void completeRejectsAnotherUsersAsset() {
        AssetRepository assets = mock(AssetRepository.class);
        IndexJobRepository jobs = mock(IndexJobRepository.class);
        MediaStorage storage = mock(MediaStorage.class);
        UUID owner = UUID.randomUUID();
        UUID assetId = UUID.randomUUID();
        Asset asset = new Asset(assetId, owner, "assets/media/file.jpg",
                MediaType.image, "Elephant", null, null, null, null, null, null,
                AssetStatus.UPLOADING);
        when(assets.findByIdForUpdate(assetId)).thenReturn(Optional.of(asset));

        assertThatThrownBy(() -> new AssetService(assets, jobs, storage)
                .complete(assetId, UUID.randomUUID()))
                .isInstanceOf(ResponseStatusException.class)
                .satisfies(e -> assertThat(((ResponseStatusException) e).getStatusCode().value())
                        .isEqualTo(403));
        verify(storage, never()).verifyUpload(anyString(), anyString());
        verify(jobs, never()).insertIfAbsent(any(), anyString(), anyString());
    }
    @Test
    void initiateInfersMediaTypeFromPublishedRequest() throws Exception {
        var request = new com.fasterxml.jackson.databind.ObjectMapper().readValue(
                """
                {"filename":"elephant.jpg","contentType":"image/jpeg","title":"Elephant"}
                """, InitiateAssetRequest.class);
        try (var validator = jakarta.validation.Validation.buildDefaultValidatorFactory()) {
            assertThat(validator.getValidator().validate(request)).isEmpty();
        }
        var assets = mock(AssetRepository.class);
        var storage = mock(MediaStorage.class);
        new AssetService(assets, mock(IndexJobRepository.class), storage)
                .initiate(request, UUID.randomUUID());
        var saved = org.mockito.ArgumentCaptor.forClass(Asset.class);
        verify(assets).insert(saved.capture());
        assertThat(saved.getValue().mediaType()).isEqualTo(MediaType.image);
    }

    @Test
    void initiateRejectsMismatchedMediaType() {
        var assets = mock(AssetRepository.class);
        var request = new InitiateAssetRequest("a.jpg", "image/jpeg", "Photo",
                null, null, null, null, null, null, MediaType.video);
        assertThatThrownBy(() -> new AssetService(assets, mock(IndexJobRepository.class),
                mock(MediaStorage.class)).initiate(request, UUID.randomUUID()))
                .isInstanceOf(ResponseStatusException.class);
        verify(assets, never()).insert(any());
    }
}
