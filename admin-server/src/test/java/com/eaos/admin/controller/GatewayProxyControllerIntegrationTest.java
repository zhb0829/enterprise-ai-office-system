package com.eaos.admin.controller;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.eaos.admin.config.AiServiceProperties;
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

class GatewayProxyControllerIntegrationTest {

  private final AtomicReference<String> upstreamMethod = new AtomicReference<>();
  private final AtomicReference<String> upstreamPath = new AtomicReference<>();
  private final AtomicReference<String> upstreamQuery = new AtomicReference<>();
  private final AtomicReference<String> upstreamBody = new AtomicReference<>();
  private final AtomicReference<String> upstreamRequestId = new AtomicReference<>();

  private HttpServer upstream;
  private MockMvc mockMvc;

  @BeforeEach
  void startUpstream() throws IOException {
    upstream = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    upstream.createContext("/", this::handleRequest);
    upstream.start();

    AiServiceProperties properties = new AiServiceProperties();
    properties.setBaseUrl("http://127.0.0.1:" + upstream.getAddress().getPort());
    mockMvc = MockMvcBuilders.standaloneSetup(new GatewayProxyController(properties)).build();
  }

  @AfterEach
  void stopUpstream() {
    if (upstream != null) {
      upstream.stop(0);
    }
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

    byte[] response = "{\"proxied\":true}".getBytes(StandardCharsets.UTF_8);
    exchange.getResponseHeaders().add("Content-Type", MediaType.APPLICATION_JSON_VALUE);
    exchange.getResponseHeaders().add("X-Upstream-Id", "upstream-123");
    exchange.sendResponseHeaders(201, response.length);
    exchange.getResponseBody().write(response);
    exchange.close();
  }
}
