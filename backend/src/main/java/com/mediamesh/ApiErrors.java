package com.mediamesh;

import java.util.Map;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.server.ResponseStatusException;

@RestControllerAdvice
public class ApiErrors {
    @ExceptionHandler(ResponseStatusException.class)
    ResponseEntity<?> status(ResponseStatusException e, jakarta.servlet.http.HttpServletRequest request) {
        if (e instanceof com.mediamesh.media.SearchFailure failure) {
            request.setAttribute(com.mediamesh.observability.SearchSliMetrics.FAILURE_ATTRIBUTE,failure.category());
            return ResponseEntity.status(e.getStatusCode()).body(Map.of("error",Map.of(
                    "code",failure.code(),"message",failure.getReason())));
        }
        return ResponseEntity.status(e.getStatusCode()).body(Map.of("error", Map.of(
                "code", "HTTP_"+e.getStatusCode().value(), "message", e.getReason()==null ? "Request failed" : e.getReason())));
    }
    @ExceptionHandler({MethodArgumentNotValidException.class, HttpMessageNotReadableException.class,
            MethodArgumentTypeMismatchException.class})
    ResponseEntity<?> invalid(Exception e) {
        return ResponseEntity.badRequest().body(Map.of("error", Map.of("code","INVALID_INPUT","message","Invalid request input")));
    }
}
