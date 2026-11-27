package com.mediamesh.observability;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.*;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE+5)
public class RequestIdFilter extends OncePerRequestFilter {
    private static final Logger LOG=LoggerFactory.getLogger(RequestIdFilter.class);
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)
            throws ServletException,IOException {
        var previous=MDC.getCopyOfContextMap();
        String incoming=request.getHeader("X-Request-ID");
        String id=incoming!=null && incoming.matches("[a-fA-F0-9-]{16,64}") ? incoming : UUID.randomUUID().toString();
        MDC.put("requestId",id);response.setHeader("X-Request-ID",id);
        long start=System.nanoTime();boolean failed=true;
        try{chain.doFilter(request,response);failed=false;}
        finally{
            LOG.info("http_request_complete method={} status={} duration_ms={}",request.getMethod(),
                    failed ? 500 : response.getStatus(),(System.nanoTime()-start)/1000000.0);
            if(previous==null) MDC.clear();else MDC.setContextMap(previous);
        }
    }
}
