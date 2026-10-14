package com.eaos.admin.controller;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.opinion.entity.OpinionReport;
import com.eaos.admin.opinion.service.OpinionReportService;
import com.eaos.admin.security.LoginUser;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.*;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

class FileDownloadControllerTest {
  private HttpServer upstream;
  private MockMvc mvc;
  private OpinionReportService reports;
  private final AtomicInteger status = new AtomicInteger(200);
  private final AtomicInteger calls = new AtomicInteger();
  private final AtomicReference<com.sun.net.httpserver.Headers> headers = new AtomicReference<>();

  @BeforeEach
  void setup() throws Exception {
    upstream = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
    upstream.createContext("/", exchange -> {
      calls.incrementAndGet();
      headers.set(exchange.getRequestHeaders());
      if (status.get() == 302) exchange.getResponseHeaders().set("Location", "/private");
      byte[] body = "report".getBytes(StandardCharsets.UTF_8);
      exchange.sendResponseHeaders(status.get(), body.length);
      exchange.getResponseBody().write(body);
      exchange.close();
    });
    upstream.start();
    var properties = new AiServiceProperties();
    properties.setBaseUrl("http://127.0.0.1:" + upstream.getAddress().getPort());
    properties.setInternalToken("trusted-token");
    reports = mock(OpinionReportService.class);
    mvc = MockMvcBuilders.standaloneSetup(new FileDownloadController(properties, reports)).build();
    var user = new LoginUser(42L, "user", "", "User", "USER", true);
    SecurityContextHolder.getContext().setAuthentication(
        new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities()));
  }

  @AfterEach
  void cleanup() {
    SecurityContextHolder.clearContext();
    upstream.stop(0);
  }

  @Test
  void reportAccessIsCheckedBeforeTrustedResourceAssertion() throws Exception {
    when(reports.get(7L)).thenReturn(new OpinionReport());
    mvc.perform(get("/api/files/upload/opinion-report_7.html")
        .header("X-Download-Resource", "opinion-report:8")
        .header("X-User-Id", "forged")
        .header("X-Tenant-Id", "forged")
        .header("X-Data-Clearance", "restricted")).andExpect(status().isOk());
    verify(reports).get(7L);
    assertEquals("opinion-report:7", headers.get().getFirst("X-Download-Resource"));
    assertEquals("42", headers.get().getFirst("X-User-Id"));
    assertEquals("default", headers.get().getFirst("X-Tenant-Id"));
    assertEquals("internal", headers.get().getFirst("X-Data-Clearance"));
    assertEquals("trusted-token", headers.get().getFirst("X-Internal-Token"));
  }

  @Test
  void forbiddenReportDoesNotReachUpstream() throws Exception {
    when(reports.get(7L)).thenThrow(new IllegalArgumentException("not visible"));
    mvc.perform(get("/api/files/upload/opinion-report_7.pdf")).andExpect(status().isNotFound());
    assertEquals(0, calls.get());
  }

  @Test
  void ordinaryFileCannotCarryBrowserSuppliedReportAssertion() throws Exception {
    mvc.perform(get("/api/files/upload/1_material.txt").header("X-Download-Resource", "opinion-report:7"))
        .andExpect(status().isOk());
    assertNull(headers.get().getFirst("X-Download-Resource"));
    verifyNoInteractions(reports);
  }

  @Test
  void rejectsTraversalAndDoesNotFollowRedirects() throws Exception {
    for (String path : new String[] {"..%2Fprivate", "%252e%252e", "folder/file", "%5cprivate", "%0d%0aheader"}) {
      mvc.perform(get(URI.create("/api/files/upload/" + path))).andExpect(status().isBadRequest());
    }
    assertEquals(0, calls.get());
    status.set(302);
    mvc.perform(get("/api/files/upload/1_material.txt")).andExpect(status().isBadGateway());
    assertEquals(1, calls.get());
  }
}
