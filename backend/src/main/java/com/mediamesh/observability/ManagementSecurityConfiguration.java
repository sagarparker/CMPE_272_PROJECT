package com.mediamesh.observability;

import org.springframework.boot.actuate.autoconfigure.security.servlet.EndpointRequest;
import org.springframework.context.annotation.*;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
public class ManagementSecurityConfiguration {
    @Bean @Order(0)
    SecurityFilterChain metricsSecurity(HttpSecurity http) throws Exception {
        // This endpoint is served only on the separate, unpublished management port.
        return http.securityMatcher(EndpointRequest.to("prometheus"))
                .authorizeHttpRequests(auth -> auth.anyRequest().permitAll()).build();
    }
}
