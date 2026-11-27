package com.mediamesh.media;
import java.time.LocalDate;
import jakarta.validation.constraints.*;
public record MetadataRequest(@NotBlank @Size(max=255) String title, @Size(max=4000) String description,
        @Size(max=255) String species, @Size(max=255) String location, LocalDate capturedAt,
        @Size(max=255) String contributor, @Size(max=4000) String usageNote) {}
