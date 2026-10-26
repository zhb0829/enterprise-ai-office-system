package com.eaos.admin.controller;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.security.LoginUser;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.slf4j.MDC;

class GatewayProxyControllerIntegrationTest {

  private final AtomicReference<String> upstreamMethod = new AtomicReference<>();
  private final AtomicReference<String> upstreamPath = new AtomicReference<>();
  private final AtomicReference<String> upstreamQuery = new AtomicReference<>();
  private final AtomicReference<String> upstreamBody = new AtomicReference<>();
  private final AtomicReference<String> upstreamRequestId = new AtomicReference<>();
  private final AtomicReference<String> upstreamUserId = new AtomicReference<>();
  private final AtomicReference<String> upstreamPermissions = new AtomicReference<>();
  private final AtomicReference<String> upstreamRole = new AtomicReference<>();
  private final AtomicReference<String> upstreamTargetTenant = new AtomicReference<>();
  private final AtomicReference<String> upstreamToken = new AtomicReference<>();
  private final AtomicReference<String> upstreamTrace = new AtomicReference<>();

  private HttpServer upstream;
  private MockMvc mockMvc;

  @BeforeEach
  void startUpstream() throws IOException {
    upstream = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    upstream.createContext("/", this::handleRequest);
    upstream.start();

    AiServiceProperties properties = new AiServiceProperties();
    properties.setBaseUrl("http://127.0.0.1:" + upstream.getAddress().getPort());
    properties.setInternalToken("trusted-test-token");
    mockMvc = MockMvcBuilders.standaloneSetup(new GatewayProxyController(properties)).build();
  }

  @AfterEach
  void stopUpstream() {
    SecurityContextHolder.clearContext();
    MDC.clear();
    if (upstream != null) {
      upstream.stop(0);
    }
  }

  @Test
  void replacesSpoofedHeadersWithTrustedIdentity() throws Exception {
    LoginUser user = new LoginUser(42L, "reviewer", "", "Reviewer", "ADMIN", true);
    SecurityContextHolder.getContext().setAuthentication(
        new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities()));
    MDC.put("traceId", "trusted-trace");
    mockMvc.perform(post("/api/agent/tools/search_policy/invoke")
            .contentType(MediaType.APPLICATION_JSON)
            .header("X-Internal-Token", "spoofed-token")
            .header("X-User-Id", "spoofed-user")
            .header("X-User-Permissions", "spoofed-permission")
            .header("X-User-Role", "member")
            .header("X-Target-Tenant", "other-tenant")
            .header("X-Trace-Id", "spoofed-trace")
            .content("{}"))
        .andExpect(status().isCreated());
    assertEquals("trusted-test-token", upstreamToken.get());
    assertEquals("42", upstreamUserId.get());
    assertTrue(upstreamPermissions.get().contains("draft:review"));
    assertTrue(upstreamPermissions.get().contains("agent:audit"));
    assertFalse(upstreamPermissions.get().contains("spoofed-permission"));
    // G7：ADMIN 账号 → platform_admin 角色，且客户端伪造的角色与跨租户头不会透传。
    assertEquals("platform_admin", upstreamRole.get());
    assertEquals(null, upstreamTargetTenant.get());
    assertEquals("trusted-trace", upstreamTrace.get());
  }

  @Test
  void anonymousRequestCannotForgeReviewerIdentity() throws Exception {
    mockMvc.perform(post("/api/drafts/draft-v1/review")
            .header("X-User-Id", "spoofed-user")
            .header("X-User-Permissions", "draft:review,agent:audit")
            .header("X-User-Role", "platform_admin")
            .content("{}"))
        .andExpect(status().isCreated());
    assertEquals(null, upstreamUserId.get());
    assertEquals(null, upstreamPermissions.get());
    // G7：匿名请求连角色头都不会下发，"自己声明成平台管理员"不成立。
    assertEquals(null, upstreamRole.get());
    assertEquals("trusted-test-token", upstreamToken.get());
  }

  @Test
  void forwardsMethodPathQueryBodyHeadersAndResponse() throws Exception {
    MvcResult result =
        mockMvc
            .perform(
                post("/api/drafts/news")
                    .queryParam("mode", "preview")
                    .contentType(MediaType.APPLICATION_JSON)
                    .header("X-Request-Id", "trace-123")
                    .content("{\"topic\":\"proxy integration\"}"))
            .andExpect(status().isCreated())
            .andExpect(header().string("X-Upstream-Id", "upstream-123"))
            .andReturn();

    assertEquals("POST", upstreamMethod.get());
    assertEquals("/api/drafts/news", upstreamPath.get());
    assertEquals("mode=preview", upstreamQuery.get());
    assertEquals("{\"topic\":\"proxy integration\"}", upstreamBody.get());
    assertEquals("trace-123", upstreamRequestId.get());
    assertTrue(result.getResponse().getContentAsString().contains("\"proxied\":true"));
  }

  private void handleRequest(HttpExchange exchange) throws IOException {
    upstreamMethod.set(exchange.getRequestMethod());
    upstreamPath.set(exchange.getRequestURI().getPath());
    upstreamQuery.set(exchange.getRequestURI().getQuery());
    upstreamBody.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
    upstreamRequestId.set(exchange.getRequestHeaders().getFirst("X-Request-Id"));
    upstreamUserId.set(exchange.getRequestHeaders().getFirst("X-User-Id"));
    upstreamPermissions.set(exchange.getRequestHeaders().getFirst("X-User-Permissions"));
    // G7：租户治理角色与跨租户目标头都只能由网关下发，客户端值必须被剥离。
    upstreamRole.set(exchange.getRequestHeaders().getFirst("X-User-Role"));
    upstreamTargetTenant.set(exchange.getRequestHeaders().getFirst("X-Target-Tenant"));
    upstreamToken.set(exchange.getRequestHeaders().getFirst("X-Internal-Token"));
    upstreamTrace.set(exchange.getRequestHeaders().getFirst("X-Trace-Id"));

    byte[] response = "{\"proxied\":true}".getBytes(StandardCharsets.UTF_8);
    exchange.getResponseHeaders().add("Content-Type", MediaType.APPLICATION_JSON_VALUE);
    exchange.getResponseHeaders().add("X-Upstream-Id", "upstream-123");
    exchange.sendResponseHeaders(201, response.length);
    exchange.getResponseBody().write(response);
    exchange.close();
  }
}
