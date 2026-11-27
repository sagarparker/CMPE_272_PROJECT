package com.mediamesh.media;

import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

public class SearchFailure extends ResponseStatusException {
    private final String code;
    private final String category;
    public SearchFailure(String code,String category) {
        super(HttpStatus.SERVICE_UNAVAILABLE,"Semantic search is temporarily unavailable");
        this.code=code;this.category=category;
    }
    public String code() {return code;}
    public String category() {return category;}
    public static SearchFailure dependency() {return new SearchFailure("ML_SEARCH_UNAVAILABLE","dependency");}
}
