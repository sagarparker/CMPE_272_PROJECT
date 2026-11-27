package com.mediamesh.media;

import jakarta.validation.Valid;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api")
@PreAuthorize("hasRole('RESEARCHER')")
public class SearchController {
    public record Result(UUID assetId,String title,MediaType mediaType,double score,Double frameTimestampSeconds,
            String species,String location,AssetStatus processingStatus) {}
    private final MlSearchClient ml;
    private final AssetRepository assets;
    public SearchController(AssetRepository assets,MlSearchClient ml) {
        this.assets=assets;this.ml=ml;
    }
    @PostMapping("/search")
    public Map<String,Object> search(@Valid @RequestBody SearchRequest request) {
        var eligible=assets.eligible(request);
        if (eligible.isEmpty()) return Map.of("results",List.of());
        return enrich(ml.search(Map.of("query",request.query(),"limit",request.resultLimit(),"assetIds",eligible)));
    }
    @PostMapping("/assets/{id}/similar")
    public Map<String,Object> similar(@PathVariable UUID id) {
        var asset=assets.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,"Asset not found"));
        if (asset.processingStatus()!=AssetStatus.READY) throw new ResponseStatusException(HttpStatus.CONFLICT,"Asset is not ready");
        return enrich(ml.similar(Map.of("assetId",id,"limit",10,
                "assetIds",assets.eligible(new SearchRequest("similar",null,null,null,null,10)))));
    }
    private Map<String,Object> enrich(MlSearchClient.Matches matches) {
        var results=new ArrayList<Result>();
        for (var match:matches.matches()) assets.findById(match.assetId()).filter(a -> a.processingStatus()==AssetStatus.READY)
            .ifPresent(a -> results.add(new Result(a.id(),a.title(),a.mediaType(),match.score(),match.frameTimestampSeconds(),
                    a.species(),a.location(),a.processingStatus())));
        return Map.of("results",results);
    }
}
