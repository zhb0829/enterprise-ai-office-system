package com.eaos.admin.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "eaos.ai")
public class AiServiceProperties {

  /** 独立 Python agent 服务内网地址，如 http://localhost:8000 */
  private String baseUrl = "http://localhost:8000";

  /** Python 侧内网接口前缀 */
  private String internalPrefix = "/internal";

  private String internalToken = "";
}
