package com.mediamesh.media;

import com.mediamesh.identity.IdentityService;
import com.mediamesh.storage.MediaStorage;
import jakarta.validation.Valid;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/assets")
public class CatalogController {
    private final AssetRepository assets;
    private final MediaStorage storage;
    private final IdentityService identities;
    public CatalogController(AssetRepository assets, MediaStorage storage, IdentityService identities) {
        this.assets=assets;this.storage=storage;this.identities=identities;
    }
    @GetMapping
    @PreAuthorize("hasRole('UPLOADER')")
    public List<AssetView> list(Authentication auth, @RequestParam(defaultValue="0") int offset) {
        if (offset<0) throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"Invalid offset");
        return assets.owned(UUID.fromString(auth.getName()),offset).stream().map(AssetView::of).toList();
    }
    @GetMapping("/{id}")
    @PreAuthorize("hasAnyRole('UPLOADER','RESEARCHER')")
    public AssetView detail(@PathVariable UUID id, Authentication auth) {
        var asset=required(id);
        boolean owner=asset.ownerId().toString().equals(auth.getName()) && role(auth,"UPLOADER");
        if (!owner && !(role(auth,"RESEARCHER") && asset.processingStatus()==AssetStatus.READY))
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,"Asset access denied");
        return AssetView.of(asset);
    }
    @PutMapping("/{id}")
    @PreAuthorize("hasRole('UPLOADER')")
    @Transactional
    public AssetView edit(@PathVariable UUID id, @Valid @RequestBody MetadataRequest body, Authentication auth) {
        var asset=assets.findByIdForUpdate(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,"Asset not found"));
        if (!asset.ownerId().toString().equals(auth.getName()))
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,"Asset is owned by another user");
        assets.update(id,body);
        return AssetView.of(required(id));
    }
    @PostMapping("/{id}/access-url")
    @PreAuthorize("hasRole('RESEARCHER')")
    @Transactional
    public Map<String,Object> access(@PathVariable UUID id, Authentication auth,
            @RequestParam(defaultValue="false") boolean download) {
        var asset=required(id);
        if (asset.processingStatus()!=AssetStatus.READY)
            throw new ResponseStatusException(HttpStatus.CONFLICT,"Asset is not ready");
        // Previews play the browser-safe copy when one exists; downloads always return the original.
        String key=!download && asset.mediaType()==MediaType.video
                ? assets.playbackKey(id).orElse(asset.objectKey()) : asset.objectKey();
        String url=storage.createAccessUrl(key,download);
        identities.audit(UUID.fromString(auth.getName()),download ? "DOWNLOAD" : "PREVIEW",id.toString(),"Signed URL issued; expires in 60 seconds");
        return Map.of("url",url,"expiresInSeconds",60);
    }
    private Asset required(UUID id) {
        return assets.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,"Asset not found"));
    }
    private boolean role(Authentication auth,String role) {
        return auth.getAuthorities().stream().anyMatch(a -> a.getAuthority().equals("ROLE_"+role));
    }
}
