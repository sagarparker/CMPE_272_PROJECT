package com.mediamesh;

import com.mediamesh.identity.IdentityService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.oauth2.core.*;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.security.web.SecurityFilterChain;
import java.io.IOException;
import jakarta.servlet.http.HttpServletResponse;

@Configuration
@EnableMethodSecurity
public class MediaMeshSecurityConfiguration {
    @Bean
    JwtDecoder jwtDecoder(@Value("${mediamesh.security.issuer}") String issuer,
            @Value("${mediamesh.security.jwk-set-uri}") String jwks,
            @Value("${mediamesh.security.audience}") String audience) {
        var transport=new org.springframework.http.client.SimpleClientHttpRequestFactory();
        transport.setConnectTimeout(1000);transport.setReadTimeout(1500);
        var decoder = NimbusJwtDecoder.withJwkSetUri(jwks)
                .restOperations(new org.springframework.web.client.RestTemplate(transport)).build();
        OAuth2TokenValidator<Jwt> audienceValidator = jwt -> jwt.getAudience().contains(audience)
                ? OAuth2TokenValidatorResult.success()
                : OAuth2TokenValidatorResult.failure(new OAuth2Error("invalid_token","Invalid audience",null));
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(
                JwtValidators.createDefaultWithIssuer(issuer), audienceValidator));
        return decoder;
    }
    @Bean
    SecurityFilterChain securityFilterChain(HttpSecurity http, IdentityService identities) throws Exception {
        http.csrf(csrf -> csrf.disable())
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth.requestMatchers("/health").permitAll().anyRequest().authenticated())
            .exceptionHandling(errors -> errors.accessDeniedHandler((request,response,error) -> error(response,403,"FORBIDDEN","Access denied")))
            .oauth2ResourceServer(oauth -> oauth.authenticationEntryPoint((request,response,error) -> error(response,401,"UNAUTHORIZED","Authentication required"))
                .accessDeniedHandler((request,response,error) -> error(response,403,"FORBIDDEN","Access denied"))
                .jwt(jwt -> jwt.jwtAuthenticationConverter(token -> {
                var user = identities.authenticate(token);
                var roles = user.roles().stream().map(role -> new SimpleGrantedAuthority("ROLE_"+role)).toList();
                return new JwtAuthenticationToken(token, roles, user.id().toString());
            })));
        return http.build();
    }
    private static void error(HttpServletResponse response,int status,String code,String message) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        if (status==401) response.setHeader("WWW-Authenticate","Bearer");
        response.getWriter().write("{\"error\":{\"code\":\""+code+"\",\"message\":\""+message+"\"}}");
    }
}
