package com.mediamesh.media;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.time.LocalDate;

public record InitiateAssetRequest(
        @NotBlank @Size(max = 255) String filename,
        @NotBlank @Size(max = 100) String contentType,
        @NotBlank @Size(max = 255) String title,
        @Size(max = 4000) String description,
        @Size(max = 255) String species,
        @Size(max = 255) String location,
        LocalDate capturedAt,
        @Size(max = 255) String contributor,
        @Size(max = 4000) String usageNote,
        MediaType mediaType
) {}
