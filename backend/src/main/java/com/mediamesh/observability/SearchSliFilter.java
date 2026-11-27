package com.mediamesh.observability;

import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE+10)
public class SearchSliFilter extends OncePerRequestFilter {
    private static final String RECORDED=SearchSliFilter.class.getName()+".recorded";
    private final SearchSliMetrics metrics;
    public SearchSliFilter(SearchSliMetrics metrics) {this.metrics=metrics;}
    @Override protected boolean shouldNotFilter(HttpServletRequest request) {
        return !"POST".equals(request.getMethod())
                || !(request.getContextPath()+"/api/search").equals(request.getRequestURI())
                || request.getAttribute(RECORDED)!=null;
    }
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,
            FilterChain chain) throws ServletException,IOException {
        long started=metrics.now();
        boolean unhandled=true;
        try {
            chain.doFilter(request,response);
            unhandled=false;
        } finally {
            // Current search is synchronous. ERROR redispatches must not record it again.
            request.setAttribute(RECORDED,Boolean.TRUE);
            metrics.record(response.getStatus(),Math.max(0,metrics.now()-started),
                    (String)request.getAttribute(SearchSliMetrics.FAILURE_ATTRIBUTE),unhandled);
        }
    }
}
