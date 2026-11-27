package com.mediamesh.observability;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.LoggingEvent;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.*;
import org.junit.jupiter.api.*;
import org.slf4j.MDC;
import org.springframework.mock.web.*;
import static org.assertj.core.api.Assertions.*;

class RequestIdFilterTest {
    @AfterEach void clear(){MDC.clear();}
    @Test void requestIdIsValidatedReturnedAndMdcIsRestored() throws Exception {
        String identity=UUID.randomUUID().toString();MDC.put("requestId","previous");
        var request=new MockHttpServletRequest("POST","/api/search");
        request.addHeader("X-Request-ID",identity);var response=new MockHttpServletResponse();
        new RequestIdFilter().doFilter(request,response,(req,res)->assertThat(MDC.get("requestId")).isEqualTo(identity));
        assertThat(response.getHeader("X-Request-ID")).isEqualTo(identity);
        assertThat(MDC.get("requestId")).isEqualTo("previous");
    }
    @Test void maliciousCorrelationHeadersAreReplaced() throws Exception {
        var request=new MockHttpServletRequest("GET","/health");
        request.addHeader("X-Request-ID","forged\nlog line");var response=new MockHttpServletResponse();
        new RequestIdFilter().doFilter(request,response,(req,res)->{});
        assertThat(UUID.fromString(response.getHeader("X-Request-ID"))).isNotNull();
        assertThat(MDC.get("requestId")).isNull();
    }
    @Test void everyEncodedLogIsOneJsonLineWithRequestId() throws Exception {
        var event=new LoggingEvent();event.setLevel(Level.INFO);event.setLoggerName("test");
        event.setMessage("first line\nsecond line");event.setMDCPropertyMap(Map.of());
        String encoded=new String(new JsonLogEncoder().encode(event),java.nio.charset.StandardCharsets.UTF_8);
        assertThat(encoded.chars().filter(c->c=='\n').count()).isEqualTo(1);
        var tree=new ObjectMapper().readTree(encoded);
        assertThat(tree.get("requestId").asText()).isEqualTo("system");
        assertThat(tree.get("message").asText()).contains("\n");
    }
}
