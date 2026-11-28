package com.mediamesh.demo;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/admin/seed")
@PreAuthorize("hasRole('ADMIN')")
public class SeedController {
    private final DemoSeedService seeds;

    public SeedController(DemoSeedService seeds) { this.seeds = seeds; }

    @GetMapping
    public DemoSeedService.Status status(@RequestParam(defaultValue = "20") int images) {
        return seeds.status(images);
    }

    public record SeedRequest(@NotNull Integer images) {}

    @PostMapping
    @ResponseStatus(HttpStatus.ACCEPTED)
    public DemoSeedService.Status start(@Valid @RequestBody SeedRequest body, Authentication auth) {
        return seeds.start(UUID.fromString(auth.getName()), body.images());
    }
}
