package com.eaos.admin.config;

import java.util.LinkedHashMap;
import java.util.Map;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * G3 网关层租户资源隔离配置：令牌桶（rps/burst）+ 并发配额。
 *
 * <p>网关是第一道防线，保证单租户打满不挤占其他租户；Python AI 服务侧另有
 * {@code app/resource_guard.py} 作为第二道防线（网关漏配或内部直连时兜底）。超限统一快速失败（429）， 不排队、不重试。
 */
@Data
@Component
@ConfigurationProperties(prefix = "eaos.rate-limit")
public class RateLimitProperties {

  /** 是否启用；关闭仅用于排障与容量测试，不作为生产默认。 */
  private boolean enabled = true;

  /** 每租户令牌补充速率（每秒）。 */
  private double rps = 50;

  /** 每租户令牌桶容量，即允许的瞬时突发。 */
  private int burst = 100;

  /** 每租户并发上限，0 表示不限。 */
  private int maxConcurrency = 32;

  /** 全局并发上限，0 表示不限。 */
  private int globalConcurrency = 128;

  /** 免限流路径前缀（逗号分隔）：健康检查、鉴权、文档与内部接口不消耗租户配额。 */
  private String exemptPaths =
      "/api/auth,/api/health,/actuator,/swagger-ui,/v3/api-docs,/internal,/error";

  /** 按租户覆盖，例如 {@code eaos.rate-limit.tenants.7.rps=5}；未覆盖项回落到全局默认。 */
  private Map<String, TenantQuota> tenants = new LinkedHashMap<>();

  /** 单个租户的配额覆盖；各项 &lt;= 0 表示回落到全局默认。 */
  @Data
  public static class TenantQuota {
    private double rps = 0;
    private int burst = 0;
    private int concurrency = 0;
  }
}