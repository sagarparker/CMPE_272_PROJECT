package com.mediamesh.identity;

import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.client.*;
import org.springframework.web.server.ResponseStatusException;

/** Creates sign-in identities through Keycloak's admin API using a service account limited to manage-users. */
@Component
public class KeycloakAccounts {
    private final RestClient http;
    private final String realm, clientId, clientSecret;

    public KeycloakAccounts(@Value("${mediamesh.keycloak.url:}") String url,
            @Value("${mediamesh.keycloak.realm:mediamesh}") String realm,
            @Value("${mediamesh.keycloak.client-id:mediamesh-provisioner}") String clientId,
            @Value("${mediamesh.keycloak.client-secret:}") String clientSecret) {
        var transport = new SimpleClientHttpRequestFactory();
        transport.setConnectTimeout(2000);
        transport.setReadTimeout(5000);
        this.http = url.isBlank() ? null : RestClient.builder().baseUrl(url).requestFactory(transport).build();
        this.realm = realm;
        this.clientId = clientId;
        this.clientSecret = clientSecret;
    }

    /** Returns the new Keycloak subject. First sign-in must change the password and enroll an authenticator. */
    public String create(String username, String email, String firstName, String lastName, String temporaryPassword) {
        var user = Map.of("username", username, "email", email, "firstName", firstName, "lastName", lastName,
                "enabled", true, "emailVerified", true,
                "requiredActions", List.of("UPDATE_PASSWORD", "CONFIGURE_TOTP"),
                "credentials", List.of(Map.of("type", "password", "value", temporaryPassword, "temporary", true)));
        try {
            var location = http().post().uri("/admin/realms/{realm}/users", realm)
                    .headers(h -> h.setBearerAuth(token())).contentType(MediaType.APPLICATION_JSON).body(user)
                    .retrieve().toBodilessEntity().getHeaders().getLocation();
            if (location == null) throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Identity service did not return the account");
            String path = location.getPath();
            return path.substring(path.lastIndexOf('/') + 1);
        } catch (HttpClientErrorException.Conflict e) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "That username or email is already in use");
        } catch (HttpClientErrorException.BadRequest e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "The identity service rejected the account details");
        } catch (RestClientException e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Identity service unavailable");
        }
    }

    /** Best-effort rollback when the application database could not record the account. */
    public void delete(String subject) {
        try {
            remove(subject);
        } catch (RuntimeException ignored) {
            // The orphaned identity has no MediaMesh roles, so it cannot reach any protected data.
        }
    }

    /** Deletes the sign-in identity and its Keycloak sessions. An already-missing identity is fine. */
    public void remove(String subject) {
        try {
            http().delete().uri("/admin/realms/{realm}/users/{id}", realm, subject)
                    .headers(h -> h.setBearerAuth(token())).retrieve().toBodilessEntity();
        } catch (HttpClientErrorException.NotFound gone) {
            // Retrying after a partial failure must still finish the application-side deletion.
        } catch (RestClientException e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Identity service unavailable");
        }
    }

    private RestClient http() {
        if (http == null || clientSecret.isBlank())
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Account creation is not configured");
        return http;
    }

    private String token() {
        var form = new LinkedMultiValueMap<String, String>();
        form.add("grant_type", "client_credentials");
        form.add("client_id", clientId);
        form.add("client_secret", clientSecret);
        Map<?, ?> body = http().post().uri("/realms/{realm}/protocol/openid-connect/token", realm)
                .contentType(MediaType.APPLICATION_FORM_URLENCODED).body(form).retrieve().body(Map.class);
        if (body == null || !(body.get("access_token") instanceof String token))
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Identity service unavailable");
        return token;
    }
}
