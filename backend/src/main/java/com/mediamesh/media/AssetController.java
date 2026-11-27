package com.mediamesh.media;

import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.UUID;

@RestController
@RequestMapping("/api/assets")
public class AssetController {
    private final AssetService assets;

    public AssetController(AssetService assets) {
        this.assets = assets;
    }

    @PostMapping("/initiate")
    @PreAuthorize("hasRole('UPLOADER')")
    public InitiateAssetResponse initiate(
            @Valid @RequestBody InitiateAssetRequest request,
            Authentication authentication) {
        return assets.initiate(request, principalUuid(authentication));
    }

    @PostMapping("/{id}/complete")
    @PreAuthorize("hasRole('UPLOADER')")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public CompleteUploadResponse complete(
            @PathVariable UUID id,
            Authentication authentication) {
        return assets.complete(id, principalUuid(authentication));
    }

    private UUID principalUuid(Authentication authentication) {
        try {
            return UUID.fromString(authentication.getName());
        } catch (RuntimeException e) {
            throw new ResponseStatusException(
                    HttpStatus.UNAUTHORIZED,
                    "Authenticated principal must be a stable UUID");
        }
    }
}
