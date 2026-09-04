package com.eaos.admin.controller;

import com.eaos.admin.config.AiServiceProperties;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 受控文件下载代理。
 *
 * <p>浏览器不再直接请求 Python 的 /static（公网网关不转发 /static），统一访问本端点： Java 完成 JWT 鉴权后，从 Python
 * 内部拉取导出/上传文件流式回传，并做路径穿越防护。
 */
@Slf4j
@RestController
@RequestMapping("/api/files")
@RequiredArgsConstructor
public class FileDownloadController {

  private static final String EXPORT_PREFIX = "/api/files/export/";
  private static final String UPLOAD_PREFIX = "/api/files/upload/";
  private static final int CONNECT_TIMEOUT_MS = 10_000;
  private static final int READ_TIMEOUT_MS = 300_000;

  private final AiServiceProperties aiProperties;

  @GetMapping({"/export/**", "/upload/**"})
  public void proxy(HttpServletRequest request, HttpServletResponse response) throws IOException {
    String uri = request.getRequestURI();
    String kind;
    String rel;
    if (uri.startsWith(EXPORT_PREFIX)) {
      kind = "exports";
      rel = uri.substring(EXPORT_PREFIX.length());
    } else if (uri.startsWith(UPLOAD_PREFIX)) {
      kind = "uploads";
      rel = uri.substring(UPLOAD_PREFIX.length());
    } else {
      response.sendError(HttpServletResponse.SC_BAD_REQUEST, "未知下载类型");
      return;
    }

    String path = URLDecoder.decode(rel, StandardCharsets.UTF_8);
    if (!isSafeRelativePath(path)) {
      log.warn("拒绝非法下载路径 kind={} path={}", kind, path);
      response.sendError(HttpServletResponse.SC_BAD_REQUEST, "非法的文件路径");
      return;
    }
    String filename = path.substring(path.lastIndexOf('/') + 1);
    if (filename.isBlank()) {
      response.sendError(HttpServletResponse.SC_BAD_REQUEST, "缺少文件名");
      return;
    }

    String target = aiProperties.getBaseUrl() + "/static/" + kind + "/" + path;
    log.info("受控下载 {} {} -> {}", kind, filename, target);
    try {
      HttpURLConnection conn = (HttpURLConnection) new URL(target).openConnection();
      conn.setRequestMethod("GET");
      conn.setInstanceFollowRedirects(true);
      conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
      conn.setReadTimeout(READ_TIMEOUT_MS);
      conn.setRequestProperty("User-Agent", "eaos-admin-file-gateway");
      int status = conn.getResponseCode();
      if (status >= 400) {
        conn.disconnect();
        response.sendError(status, "文件不存在或不可用");
        return;
      }
      response.setContentType(contentType(filename));
      response.setCharacterEncoding(StandardCharsets.UTF_8.name());
      String disposition =
          "inline; filename=\""
              + safeHeader(filename)
              + "\"; filename*=UTF-8''"
              + percentEncode(filename);
      response.setHeader(HttpHeaders.CONTENT_DISPOSITION, disposition);
      response.setHeader(HttpHeaders.CACHE_CONTROL, "no-store");
      try (InputStream in = conn.getInputStream();
          OutputStream out = response.getOutputStream()) {
        in.transferTo(out);
      }
      conn.disconnect();
    } catch (IOException exc) {
      log.error("受控下载失败 {}: {}", target, exc.getMessage());
      if (!response.isCommitted()) {
        response.sendError(HttpServletResponse.SC_BAD_GATEWAY, "文件服务暂时不可用");
      }
    }
  }

  private boolean isSafeRelativePath(String path) {
    if (path == null || path.isEmpty()) return false;
    if (path.contains("\0") || path.startsWith("/") || path.matches("^[a-zA-Z]:.*")) return false;
    for (String segment : path.split("/")) {
      if (segment.equals("..") || segment.equals(".")) return false;
    }
    return true;
  }

  private String contentType(String filename) {
    String lower = filename.toLowerCase(Locale.ROOT);
    if (lower.endsWith(".pdf")) return MediaType.APPLICATION_PDF_VALUE;
    if (lower.endsWith(".html") || lower.endsWith(".htm")) return "text/html";
    if (lower.endsWith(".md")) return "text/markdown; charset=utf-8";
    if (lower.endsWith(".docx")) {
      return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    }
    if (lower.endsWith(".doc")) return MediaType.APPLICATION_OCTET_STREAM_VALUE;
    if (lower.endsWith(".txt")) return "text/plain; charset=utf-8";
    return MediaType.APPLICATION_OCTET_STREAM_VALUE;
  }

  private String safeHeader(String value) {
    return value.replace("\"", "").replace("\r", "").replace("\n", "");
  }

  private String percentEncode(String value) {
    return java.net.URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20");
  }
}
