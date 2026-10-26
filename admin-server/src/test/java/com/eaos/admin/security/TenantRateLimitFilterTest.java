package com.eaos.admin.security;

import static org.assertj.core.api.Assertions.assertThat;

import com.eaos.admin.config.RateLimitProperties;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import jakarta.servlet.FilterChain;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

/** G3 网关限流：配额内放行、超限快速失败、租户之间互不挤占。 */
class TenantRateLimitFilterTest {

  private final SimpleMeterRegistry registry = new SimpleMeterRegistry();

  private RateLimitProperties properties() {
    RateLimitProperties properties = new RateLimitProperties();
    properties.setEnabled(true);
    properties.setRps(1);
    properties.setBurst(2);
    properties.setMaxConcurrency(32);
    properties.setGlobalConcurrency(0);
    return properties;
  }

  private TenantRateLimitFilter filter(RateLimitProperties properties) {
    return new TenantRateLimitFilter(properties, registry);
  }

  private void authenticate(Long tenantId) {
    LoginUser user = new LoginUser(1L, "u1", "pwd", "nick", "USER", tenantId, true);
    SecurityContextHolder.getContext()
        .setAuthentication(
            new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities()));
  }

  private MockHttpServletRequest request(String uri) {
    MockHttpServletRequest request = new MockHttpServletRequest("POST", uri);
    request.setRequestURI(uri);
    return request;
  }

  @AfterEach
  void clearContext() {
    SecurityContextHolder.clearContext();
  }

  @Test
  void allowsRequestsWithinBurstQuota() throws Exception {
    authenticate(7L);
    TenantRateLimitFilter filter = filter(properties());
    AtomicInteger calls = new AtomicInteger();
    FilterChain chain = (req, res) -> calls.incrementAndGet();

    for (int index = 0; index < 2; index++) {
      MockHttpServletResponse response = new MockHttpServletResponse();
      filter.doFilter(request("/api/policy/chat"), response, chain);
      assertThat(response.getStatus()).isEqualTo(200);
    }
    assertThat(calls.get()).isEqualTo(2);
  }

  @Test
  void throttlesBeyondBurstWithRetryAfter() throws Exception {
    authenticate(7L);
    TenantRateLimitFilter filter = filter(properties());
    AtomicInteger calls = new AtomicInteger();
    FilterChain chain = (req, res) -> calls.incrementAndGet();

    for (int index = 0; index < 2; index++) {
      filter.doFilter(request("/api/policy/chat"), new MockHttpServletResponse(), chain);
    }
    MockHttpServletResponse rejected = new MockHttpServletResponse();
    filter.doFilter(request("/api/policy/chat"), rejected, chain);

    assertThat(rejected.getStatus()).isEqualTo(429);
    assertThat(rejected.getHeader("Retry-After")).isNotBlank();
    assertThat(rejected.getHeader("X-RateLimit-Remaining")).isEqualTo("0");
    assertThat(rejected.getContentAsString()).contains("tenant_rate");
    assertThat(calls.get()).isEqualTo(2);
  }

  @Test
  void isolatesTenantsFromEachOther() throws Exception {
    TenantRateLimitFilter filter = filter(properties());
    AtomicInteger calls = new AtomicInteger();
    FilterChain chain = (req, res) -> calls.incrementAndGet();

    authenticate(7L);
    for (int index = 0; index < 3; index++) {
      filter.doFilter(request("/api/policy/chat"), new MockHttpServletResponse(), chain);
    }
    // 7 号租户已被限流，10 号租户仍应正常放行
    authenticate(10L);
    MockHttpServletResponse other = new MockHttpServletResponse();
    filter.doFilter(request("/api/policy/chat"), other, chain);
    assertThat(other.getStatus()).isEqualTo(200);

    authenticate(7L);
    MockHttpServletResponse noisy = new MockHttpServletResponse();
    filter.doFilter(request("/api/policy/chat"), noisy, chain);
    assertThat(noisy.getStatus()).isEqualTo(429);
  }

  @Test
  void tenantConcurrencyQuotaRejectsNestedRequest() throws Exception {
    authenticate(3L);
    RateLimitProperties properties = properties();
    properties.setBurst(1000);
    properties.setMaxConcurrency(1);
    TenantRateLimitFilter filter = filter(properties);
    MockHttpServletResponse inner = new MockHttpServletResponse();
    FilterChain chain =
        (req, res) -> filter.doFilter(request("/api/policy/chat"), inner, (r, s) -> {});

    MockHttpServletResponse outer = new MockHttpServletResponse();
    filter.doFilter(request("/api/policy/chat"), outer, chain);

    assertThat(outer.getStatus()).isEqualTo(200);
    assertThat(inner.getStatus()).isEqualTo(429);
    assertThat(inner.getContentAsString()).contains("tenant_concurrency");
  }

  @Test
  void exemptPathsAndDisabledSwitchBypassLimits() throws Exception {
    authenticate(4L);
    RateLimitProperties properties = properties();
    TenantRateLimitFilter filter = filter(properties);
    AtomicInteger calls = new AtomicInteger();
    FilterChain chain = (req, res) -> calls.incrementAndGet();

    for (int index = 0; index < 5; index++) {
      MockHttpServletResponse health = new MockHttpServletResponse();
      filter.doFilter(request("/api/health"), health, chain);
      assertThat(health.getStatus()).isEqualTo(200);
    }

    properties.setEnabled(false);
    for (int index = 0; index < 5; index++) {
      MockHttpServletResponse open = new MockHttpServletResponse();
      filter.doFilter(request("/api/policy/chat"), open, chain);
      assertThat(open.getStatus()).isEqualTo(200);
    }
    assertThat(calls.get()).isEqualTo(10);
  }

  @Test
  void tenantOverridesApplyToNamedTenant() throws Exception {
    authenticate(9L);
    RateLimitProperties properties = properties();
    properties.setBurst(100);
    RateLimitProperties.TenantQuota quota = new RateLimitProperties.TenantQuota();
    quota.setBurst(1);
    quota.setRps(0.001);
    properties.getTenants().put("9", quota);
    TenantRateLimitFilter filter = filter(properties);
    AtomicInteger calls = new AtomicInteger();
    FilterChain chain = (req, res) -> calls.incrementAndGet();

    MockHttpServletResponse first = new MockHttpServletResponse();
    filter.doFilter(request("/api/policy/chat"), first, chain);
    MockHttpServletResponse second = new MockHttpServletResponse();
    filter.doFilter(request("/api/policy/chat"), second, chain);

    assertThat(first.getStatus()).isEqualTo(200);
    assertThat(second.getStatus()).isEqualTo(429);
  }
}