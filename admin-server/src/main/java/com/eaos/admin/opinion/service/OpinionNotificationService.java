package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.notification.NotificationService;
import com.eaos.admin.opinion.config.OpinionServiceProperties;
import com.eaos.admin.opinion.entity.OpinionAlertEvent;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import com.eaos.admin.opinion.entity.OpinionNotification;
import com.eaos.admin.opinion.mapper.OpinionMonitorMapper;
import com.eaos.admin.opinion.mapper.OpinionNotificationMapper;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Slf4j
@Service
@RequiredArgsConstructor
public class OpinionNotificationService {

  private final OpinionNotificationMapper notificationMapper;
  private final OpinionMonitorMapper monitorMapper;
  private final RestTemplate restTemplate;
  private final OpinionServiceProperties properties;
  private final NotificationService notificationService;

  public void notifyAlert(OpinionAlertEvent alert, Long monitorId, Map<String, Object> stats) {
    OpinionMonitor monitor = monitorId == null ? null : monitorMapper.selectById(monitorId);
    String name = monitor == null ? "" : monitor.getName();
    String content =
        String.format(
            "%s %s 舆情告警: %s (触发 %s 次)",
            alert.getRiskLevel(), name, statsSummary(stats), alert.getTriggerCount());
    createNotification(alert.getId(), "站内", "", content, "success", null);
    // 消息中心（Q19）：舆情告警同步推送到监控任务负责人的站内信
    if (monitor != null) {
      notificationService.publish(
          monitor.getUserId(),
          "opinion_alert",
          "舆情告警：" + name,
          content,
          "opinion_alert",
          alert.getId());
    }

    String webhookUrl = properties.getWebhookUrl();
    if (webhookUrl != null && !webhookUrl.isBlank()) {
      OpinionNotification notification =
          createNotification(
              alert.getId(),
              "webhook",
              webhookUrl,
              webhookPayload(alert, name).toString(),
              "pending",
              null);
      deliverWebhook(notification);
    }
  }

  @Scheduled(fixedDelayString = "${OPINION_NOTIFICATION_RETRY_DELAY_MS:30000}")
  public void retryFailedNotifications() {
    List<OpinionNotification> due =
        notificationMapper.selectList(
            Wrappers.<OpinionNotification>lambdaQuery()
                .in(OpinionNotification::getStatus, "failed", "pending")
                .lt(
                    OpinionNotification::getRetryCount,
                    Math.max(1, properties.getNotificationMaxRetries()))
                .and(
                    w ->
                        w.isNull(OpinionNotification::getNextRetryAt)
                            .or()
                            .le(OpinionNotification::getNextRetryAt, LocalDateTime.now()))
                .orderByAsc(OpinionNotification::getId)
                .last("LIMIT 50"));
    due.forEach(this::deliverWebhook);
  }

  private void deliverWebhook(OpinionNotification notification) {
    if (!"webhook".equalsIgnoreCase(notification.getChannel())
        || notification.getTarget() == null
        || notification.getTarget().isBlank()) {
      return;
    }
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("event", "opinion.alert");
    payload.put("notificationId", notification.getId());
    payload.put("content", notification.getContent());
    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    try {
      restTemplate.postForObject(
          notification.getTarget(), new HttpEntity<>(payload, headers), String.class);
      notification.setStatus("success");
      notification.setError("");
      notification.setSentAt(LocalDateTime.now());
      notification.setNextRetryAt(null);
    } catch (Exception e) {
      String message = String.valueOf(e.getMessage());
      int retry = (notification.getRetryCount() == null ? 0 : notification.getRetryCount()) + 1;
      notification.setRetryCount(retry);
      notification.setError(message.substring(0, Math.min(1000, message.length())));
      if (retry >= Math.max(1, properties.getNotificationMaxRetries())) {
        notification.setStatus("failed");
        notification.setNextRetryAt(null);
      } else {
        notification.setStatus("pending");
        notification.setNextRetryAt(LocalDateTime.now().plusMinutes(1L << Math.min(retry - 1, 5)));
      }
    }
    notificationMapper.updateById(notification);
  }

  private Map<String, Object> webhookPayload(OpinionAlertEvent alert, String monitorName) {
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("event", "opinion.alert");
    payload.put("alertId", alert.getId());
    payload.put("monitor", monitorName);
    payload.put("riskLevel", alert.getRiskLevel());
    payload.put("state", alert.getState());
    payload.put("triggerStats", alert.getTriggerStats());
    payload.put("triggeredAt", alert.getLastTriggeredAt());
    return payload;
  }

  private String statsSummary(Map<String, Object> stats) {
    if (stats == null || stats.isEmpty()) {
      return "触发";
    }
    return String.format(
        "负面 %s / %s, 比例 %s, 来源 %s, 增长 %s",
        stats.get("negativeCount"),
        stats.get("totalCount"),
        stats.get("negativeRatio"),
        stats.get("sourceCount"),
        stats.get("growthRate"));
  }

  private OpinionNotification createNotification(
      Long alertId, String channel, String target, String content, String status, String error) {
    OpinionNotification notification = new OpinionNotification();
    notification.setAlertId(alertId);
    notification.setChannel(channel);
    notification.setTarget(target);
    notification.setContent(content);
    notification.setStatus(status);
    notification.setRetryCount(0);
    notification.setError(error == null ? "" : error);
    if ("success".equals(status)) {
      notification.setSentAt(LocalDateTime.now());
    }
    notificationMapper.insert(notification);
    return notification;
  }
}
