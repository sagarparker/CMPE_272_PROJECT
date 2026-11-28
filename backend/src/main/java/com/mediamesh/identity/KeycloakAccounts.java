package com.mediamesh.identity;

import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.*;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.web.client.*;
import org.springframework.web.server.ResponseStatusException;

/** Retires sign-in identities through Keycloak's admin API using a service account limited to manage-users. */
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
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "Identity administration is not configured");
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
