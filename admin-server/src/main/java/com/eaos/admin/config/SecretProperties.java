package com.eaos.admin.config;

import jakarta.annotation.PostConstruct;
import java.util.List;
import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.StringUtils;

/** 全部服务间/JWT 密钥的集中校验（Q5）：启动时检测到空值或默认占位值即拒绝启动， 防止带默认密钥的镜像被误投生产。 */
@Data
@ConfigurationProperties(prefix = "eaos")
public class SecretProperties {

  private Jwt jwt = new Jwt();
  private Ai ai = new Ai();
  private Opinion opinion = new Opinion();
  private Meeting meeting = new Meeting();

  @Data
  public static class Jwt {
    private String secret;
    private long expireMinutes = 120;
    private long refreshExpireDays = 7;
  }

  @Data
  public static class Ai {
    private String internalToken;
  }

  @Data
  public static class Opinion {
    private String internalToken;
  }

  @Data
  public static class Meeting {
    private String internalToken;
  }

  private static final List<String> FORBIDDEN_DEFAULTS =
      List.of(
          "eaos-dev-secret-key-change-me-in-production-0123456789",
          "eaos-internal-token-change-me",
          "eaos-opinion-internal-dev-token",
          "eaos-meeting-internal-dev-token");

  @PostConstruct
  void validate() {
    check("eaos.jwt.secret (JWT_SECRET)", jwt.secret, 32);
    check("eaos.ai.internal-token (AI_INTERNAL_TOKEN)", ai.internalToken, 16);
    check("eaos.opinion.internal-token (OPINION_INTERNAL_TOKEN)", opinion.internalToken, 16);
    check("eaos.meeting.internal-token (MEETING_INTERNAL_TOKEN)", meeting.internalToken, 16);
  }

  private void check(String name, String value, int minLength) {
    if (!StringUtils.hasText(value)) {
      throw new IllegalStateException("密钥未配置，拒绝启动：" + name + "。请通过环境变量或 .env 注入。");
    }
    if (value.length() < minLength) {
      throw new IllegalStateException("密钥强度不足（要求 >= " + minLength + " 字符）：" + name);
    }
    String lowered = value.toLowerCase();
    if (lowered.contains("change-me")) {
      throw new IllegalStateException("检测到默认占位密钥，拒绝启动：" + name);
    }
    if (FORBIDDEN_DEFAULTS.contains(value)) {
      throw new IllegalStateException("检测到历史默认密钥，拒绝启动：" + name);
    }
  }
}
