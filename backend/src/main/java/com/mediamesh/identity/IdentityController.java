package com.mediamesh.identity;

import java.util.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import org.springframework.http.HttpStatus;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.*;

@RestController
public class IdentityController {
    private final IdentityService identities;
    public IdentityController(IdentityService identities) { this.identities = identities; }
    @GetMapping("/api/me")
    public IdentityService.User me(Authentication auth) { return identities.user(UUID.fromString(auth.getName())); }
    @PostMapping("/api/logout")
    public void logout(JwtAuthenticationToken auth) {
        identities.logout(auth.getToken().getClaimAsString("sid"), UUID.fromString(auth.getName()));
    }
    @GetMapping("/api/admin/users")
    @PreAuthorize("hasRole('ADMIN')")
    public List<IdentityService.User> users() { return identities.users(); }
    public record AccessRequest(@NotEmpty Set<IdentityService.@NotNull Role> roles) {}
    @PostMapping("/api/me/access-request")
    @ResponseStatus(HttpStatus.CREATED)
    public IdentityService.User requestAccess(@Valid @RequestBody AccessRequest body, Authentication auth) {
        return identities.requestAccess(UUID.fromString(auth.getName()), body.roles());
    }
    @GetMapping("/api/admin/access-requests")
    @PreAuthorize("hasRole('ADMIN')")
    public List<IdentityService.AccessRequest> requests() { return identities.requests(); }
    public record Decision(@NotNull Boolean approve) {}
    @PostMapping("/api/admin/access-requests/{id}/decision")
    @PreAuthorize("hasRole('ADMIN')")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void decide(@PathVariable UUID id, @Valid @RequestBody Decision body, Authentication auth) {
        identities.decide(UUID.fromString(auth.getName()), id, body.approve());
    }
    @DeleteMapping("/api/admin/users/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable UUID id, Authentication auth) {
        identities.deleteUser(UUID.fromString(auth.getName()), id);
    }
    public record RoleRequest(@NotNull Set<IdentityService.@NotNull Role> roles) {}
    @PutMapping("/api/admin/users/{id}/roles")
    @PreAuthorize("hasRole('ADMIN')")
    public IdentityService.User roles(@PathVariable UUID id, @Valid @RequestBody RoleRequest body, Authentication auth) {
        return identities.replaceRoles(UUID.fromString(auth.getName()), id, body.roles());
    }
}
