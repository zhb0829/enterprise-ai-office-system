package com.eaos.admin.controller;

import com.eaos.admin.config.AiServiceProperties;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Enumeration;
import java.util.List;
import java.util.Set;

/**
 * 网关反向代理：将业务/AI 接口原样转发给 Python AI 服务（ai-server）。
 * 认证与权限在 Spring Security 层完成，此处仅做协议级转发（方法/路径/查询串/请求体/关键请求头透传，响应流式返回）。
 */
@Slf4j
@RestController
@RequiredArgsConstructor
public class GatewayProxyController {

    /** 由 HTTP 协议逐跳处理、不得转发的头 */
    private static final Set<String> HOP_BY_HOP = Set.of(
            "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
            "te", "trailer", "transfer-encoding", "upgrade", "host");

    /** 需要转发给 Python AI 服务的路径前缀（与前端 api.js 调用保持一致） */
    private static final List<String> PROXY_PREFIXES =
            List.of("/api/templates", "/api/drafts", "/api/materials");

    private final AiServiceProperties aiServiceProperties;

    @RequestMapping({"/api/templates/**", "/api/drafts/**", "/api/materials/**"})
    public void proxy(HttpServletRequest request, HttpServletResponse response) throws IOException {
        String path = request.getRequestURI();
        String query = request.getQueryString();
        String target = aiServiceProperties.getBaseUrl() + path + (query == null ? "" : "?" + query);
        log.info("网关转发 {} {} -> {}", request.getMethod(), path, target);

        HttpURLConnection conn = (HttpURLConnection) new URL(target).openConnection();
        conn.setRequestMethod(request.getMethod());
        conn.setInstanceFollowRedirects(false);

        copyRequestHeaders(request, conn);

        boolean hasBody = !"GET".equalsIgnoreCase(request.getMethod())
                && !"HEAD".equalsIgnoreCase(request.getMethod())
                && request.getContentLength() != 0;
        conn.setDoOutput(hasBody);
        if (hasBody) {
            int contentLength = request.getContentLength();
            if (contentLength > 0) {
                conn.setFixedLengthStreamingMode(contentLength);
            } else {
                conn.setChunkedStreamingMode(0);
            }
            try (InputStream body = request.getInputStream();
                 OutputStream out = conn.getOutputStream()) {
                body.transferTo(out);
            }
        }

        int status = conn.getResponseCode();
        response.setStatus(status);
        copyResponseHeaders(conn, response);

        try (InputStream in = status >= 400 ? conn.getErrorStream() : conn.getInputStream()) {
            if (in != null) {
                in.transferTo(response.getOutputStream());
            }
        }
        conn.disconnect();
    }

    private void copyRequestHeaders(HttpServletRequest request, HttpURLConnection conn) {
        Enumeration<String> names = request.getHeaderNames();
        while (names.hasMoreElements()) {
            String name = names.nextElement();
            if (HOP_BY_HOP.contains(name.toLowerCase())) {
                continue;
            }
            Enumeration<String> values = request.getHeaders(name);
            while (values.hasMoreElements()) {
                conn.addRequestProperty(name, values.nextElement());
            }
        }
    }

    private void copyResponseHeaders(HttpURLConnection conn, HttpServletResponse response) {
        for (java.util.Map.Entry<String, List<String>> entry : conn.getHeaderFields().entrySet()) {
            String name = entry.getKey();
            if (name == null || HOP_BY_HOP.contains(name.toLowerCase())) {
                continue;
            }
            for (String value : entry.getValue()) {
                response.addHeader(name, value);
            }
        }
    }
}