package com.mediamesh.media;

import jakarta.validation.Valid;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
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
    private final double minSearchSimilarity;
    public SearchController(AssetRepository assets,MlSearchClient ml,
            @Value("${mediamesh.ml.search-min-similarity}") double minSearchSimilarity) {
        if (!(minSearchSimilarity >= -1 && minSearchSimilarity <= 1)) {
            throw new IllegalArgumentException("ML_SEARCH_MIN_SIMILARITY must be between -1 and 1");
        }
        this.assets=assets;this.ml=ml;
        this.minSearchSimilarity=minSearchSimilarity;
    }
    @PostMapping("/search")
    public Map<String,Object> search(@Valid @RequestBody SearchRequest request) {
        var eligible=assets.eligible(request);
        if (eligible.isEmpty()) return Map.of("results",List.of());
        var matches=ml.search(Map.of("query",request.query(),"limit",request.resultLimit(),"assetIds",eligible));
        return enrich(matches.matches());
    }
    @PostMapping("/assets/{id}/similar")
    public Map<String,Object> similar(@PathVariable UUID id) {
        var asset=assets.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND,"Asset not found"));
        if (asset.processingStatus()!=AssetStatus.READY) throw new ResponseStatusException(HttpStatus.CONFLICT,"Asset is not ready");
        var matches=ml.similar(Map.of("assetId",id,"limit",10,
                "assetIds",assets.eligible(new SearchRequest("similar",null,null,null,null,10))));
        return enrich(matches.matches());
    }
    private Map<String,Object> enrich(List<MlSearchClient.Match> matches) {
        var results=new ArrayList<Result>();
        for (var match:matches.stream().filter(match -> match.score() >= minSearchSimilarity).toList()) assets.findById(match.assetId()).filter(a -> a.processingStatus()==AssetStatus.READY)
            .ifPresent(a -> results.add(new Result(a.id(),a.title(),a.mediaType(),match.score(),match.frameTimestampSeconds(),
                    a.species(),a.location(),a.processingStatus())));
        return Map.of("results",results);
    }
}
