package com.eaos.admin.opinion.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

@Data
@Component
@ConfigurationProperties(prefix = "eaos.opinion")
public class OpinionServiceProperties {

  /** 服务间共享令牌：Python Worker 调用本服务内部接口的 X-Internal-Token 校验值 */
  private String internalToken = "";

  /** 单次采集最多推送条目数 */
  private int maxItemsPerIngest = 200;

  /** 一次采集任务触发的分析任务数上限（防止任务爆炸） */
  private int maxAnalysisJobsPerCollect = 200;

  private int maxAnalysisRetries = 3;

  private int staleTaskMinutes = 15;

  private int notificationMaxRetries = 3;

  private boolean autoReportEnabled = true;

  /** 告警 Webhook 回调地址（可选），为空则不发送 */
  private String webhookUrl = "";
}
