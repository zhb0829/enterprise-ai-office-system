package com.eaos.admin.security;

import com.eaos.admin.config.RateLimitProperties;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.MediaType;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * G3 网关层租户资源隔离：按租户令牌桶限流 + 并发配额，超限快速失败（429）。
 *
 * <p>三个刻意的选择：
 *
 * <ul>
 *   <li><b>只按可信身份分租户</b>：租户键取自 JWT 认证出的 {@link LoginUser#getTenantId()}，客户端自报的
 *       组织头一律不参与配额计算（与 {@link AiGatewayIdentity} 的"身份只来自认证上下文"一致）。
 *   <li><b>执行位置在认证之后</b>：{@code @Order(Ordered.LOWEST_PRECEDENCE)} 使其晚于 Spring Security
 *       过滤器链执行，未认证请求不会被记到某个租户头上；鉴权失败也不会被伪装成限流。
 *   <li><b>快速失败而非排队</b>：令牌不足或并发超限立即 429 + {@code Retry-After}，避免慢租户把线程池占满。
 * </ul>
 *
 * <p>当前账户模型尚未把 {@code X-Tenant-Id} 透传为多租户（{@link AiGatewayIdentity} 仍固定 default），
 * 因此本过滤器只做限流维度隔离，不改变既有数据隔离契约；多租户账户模型落地后无需改动本类。
 */
@Slf4j
@Component
@Order(Ordered.LOWEST_PRECEDENCE)
public class TenantRateLimitFilter extends OncePerRequestFilter {

  private final RateLimitProperties properties;
  private final Map<String, TokenBucket> buckets = new ConcurrentHashMap<>();
  private final Map<String, AtomicInteger> tenantInflight = new ConcurrentHashMap<>();
  private final AtomicInteger globalInflight = new AtomicInteger();
  private final Counter throttled;
  private final Counter passed;

  public TenantRateLimitFilter(RateLimitProperties properties, MeterRegistry registry) {
    this.properties = properties;
    this.throttled =
        Counter.builder("eaos_gateway_tenant_throttled_total")
            .description("Gateway requests rejected by tenant resource isolation")
            .register(registry);
    this.passed =
        Counter.builder("eaos_gateway_tenant_passed_total")
            .description("Gateway requests admitted by tenant resource isolation")
            .register(registry);
    Gauge.builder("eaos_gateway_inflight", globalInflight, AtomicInteger::doubleValue)
        .description("Gateway in-flight requests counted by tenant isolation")
        .register(registry);
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
      throws ServletException, IOException {
    if (!properties.isEnabled() || isExempt(request.getRequestURI())) {
      filterChain.doFilter(request, response);
      return;
    }
    String tenant = tenantKey();
    RateLimitProperties.TenantQuota quota = quotaFor(tenant);
    if (!tryAcquire(globalInflight, properties.getGlobalConcurrency())) {
      reject(response, tenant, "global_concurrency", 0.05);
      return;
    }
    if (!tryAcquire(counterFor(tenant), quota.getConcurrency())) {
      release(globalInflight);
      reject(response, tenant, "tenant_concurrency", 0.05);
      return;
    }
    TokenBucket bucket =
        buckets.computeIfAbsent(
            tenant, key -> new TokenBucket(resolveRps(quota), resolveBurst(quota)));
    double retryAfter = bucket.tryConsume();
    if (retryAfter > 0) {
      release(counterFor(tenant));
      release(globalInflight);
      reject(response, tenant, "tenant_rate", retryAfter);
      return;
    }
    try {
      response.setHeader("X-RateLimit-Limit", String.valueOf((long) resolveRps(quota)));
      response.setHeader("X-Tenant-Concurrency-Limit", String.valueOf(quota.getConcurrency()));
      passed.increment();
      filterChain.doFilter(request, response);
    } finally {
      release(counterFor(tenant));
      release(globalInflight);
    }
  }

  private boolean isExempt(String path) {
    if (!StringUtils.hasText(path)) {
      return true;
    }
    for (String prefix : properties.getExemptPaths().split(",")) {
      String trimmed = prefix.trim();
      if (!trimmed.isEmpty() && path.startsWith(trimmed)) {
        return true;
      }
    }
    return false;
  }

  /** 限流维度只取认证身份；未认证请求归入 anonymous 桶，避免匿名流量无限占用资源。 */
  private String tenantKey() {
    Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
    if (authentication != null
        && authentication.isAuthenticated()
        && authentication.getPrincipal() instanceof LoginUser user
        && user.getTenantId() != null) {
      return "tenant:" + user.getTenantId();
    }
    return "anonymous";
  }

  private RateLimitProperties.TenantQuota quotaFor(String tenant) {
    RateLimitProperties.TenantQuota override = matchOverride(tenant);
    RateLimitProperties.TenantQuota effective = new RateLimitProperties.TenantQuota();
    effective.setRps(override != null && override.getRps() > 0 ? override.getRps() : properties.getRps());
    effective.setBurst(
        override != null && override.getBurst() > 0 ? override.getBurst() : properties.getBurst());
    effective.setConcurrency(
        override != null && override.getConcurrency() > 0
            ? override.getConcurrency()
            : properties.getMaxConcurrency());
    return effective;
  }

  private RateLimitProperties.TenantQuota matchOverride(String tenant) {
    if (properties.getTenants().isEmpty()) {
      return null;
    }
    // 支持 "tenant:7" 与 "7" 两种写法，运维不必记住内部前缀
    for (String key : new String[] {tenant, tenant.startsWith("tenant:") ? tenant.substring(7) : tenant}) {
      RateLimitProperties.TenantQuota quota = properties.getTenants().get(key);
      if (quota != null) {
        return quota;
      }
    }
    return null;
  }

  private double resolveRps(RateLimitProperties.TenantQuota quota) {
    return Math.max(1e-6, quota.getRps());
  }

  private int resolveBurst(RateLimitProperties.TenantQuota quota) {
    return Math.max(1, quota.getBurst());
  }

  private AtomicInteger counterFor(String tenant) {
    return tenantInflight.computeIfAbsent(tenant, key -> new AtomicInteger());
  }

  private boolean tryAcquire(AtomicInteger counter, int limit) {
    while (true) {
      int current = counter.get();
      if (limit > 0 && current >= limit) {
        return false;
      }
      if (counter.compareAndSet(current, current + 1)) {
        return true;
      }
    }
  }

  private void release(AtomicInteger counter) {
    while (true) {
      int current = counter.get();
      if (current <= 0) {
        return;
      }
      if (counter.compareAndSet(current, current - 1)) {
        return;
      }
    }
  }

  private void reject(
      HttpServletResponse response, String tenant, String reason, double retryAfterSeconds)
      throws IOException {
    long retryAfter = Math.max(1, (long) Math.ceil(retryAfterSeconds));
    throttled.increment();
    log.warn("网关租户配额拒绝 tenant={} reason={} retryAfter={}s", tenant, reason, retryAfter);
    response.setStatus(429);
    response.setHeader("Retry-After", String.valueOf(retryAfter));
    response.setHeader("X-RateLimit-Remaining", "0");
    response.setContentType(MediaType.APPLICATION_JSON_VALUE);
    response.setCharacterEncoding(StandardCharsets.UTF_8.name());
    response
        .getWriter()
        .write(
            "{\"code\":429,\"message\":\"租户配额已用尽，请稍后重试\",\"data\":{\"reason\":\""
                + reason
                + "\",\"tenant\":\""
                + tenant
                + "\"}}");
  }

  /** 标准令牌桶：容量 burst，按 rps 补充；返回 0 表示放行，正数为建议等待秒数。 */
  private static final class TokenBucket {
    private final double rate;
    private final double capacity;
    private double tokens;
    private long updatedNanos;

    TokenBucket(double rate, int burst) {
      this.rate = Math.max(1e-6, rate);
      this.capacity = Math.max(1, burst);
      this.tokens = this.capacity;
      this.updatedNanos = System.nanoTime();
    }

    synchronized double tryConsume() {
      refill();
      if (tokens >= 1.0) {
        tokens -= 1.0;
        return 0.0;
      }
      return (1.0 - tokens) / rate;
    }

    private void refill() {
      long now = System.nanoTime();
      double elapsedSeconds = Math.max(0.0, (now - updatedNanos) / 1_000_000_000.0);
      updatedNanos = now;
      tokens = Math.min(capacity, tokens + elapsedSeconds * rate);
    }
  }
}