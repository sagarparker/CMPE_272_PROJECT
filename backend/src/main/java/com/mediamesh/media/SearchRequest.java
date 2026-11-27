package com.mediamesh.media;
import jakarta.validation.constraints.*;
import java.time.LocalDate;
public record SearchRequest(@NotBlank @Size(max=1000) String query,
        MediaType mediaType, @Size(max=255) String location, @Size(max=255) String species,
        LocalDate capturedAfter, @Min(1) @Max(100) Integer limit) {
    public int resultLimit() { return limit == null ? 10 : limit; }
}
