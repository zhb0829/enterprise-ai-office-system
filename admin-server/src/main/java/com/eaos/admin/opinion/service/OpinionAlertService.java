package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.dto.AlertHandleRequest;
import com.eaos.admin.opinion.entity.OpinionAlertEvent;
import com.eaos.admin.opinion.entity.OpinionNotification;
import com.eaos.admin.opinion.mapper.OpinionAlertEventMapper;
import com.eaos.admin.opinion.mapper.OpinionNotificationMapper;
import com.eaos.admin.opinion.support.OpinionAccessService;
import com.eaos.admin.opinion.support.OpinionAuditService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class OpinionAlertService {

  private static final Set<String> STATES =
      Set.of("triggered", "acknowledged", "processing", "resolved", "closed");

  private final OpinionAlertEventMapper eventMapper;
  private final OpinionNotificationMapper notificationMapper;
  private final OpinionAuditService auditService;
  private final OpinionAccessService accessService;

  public List<OpinionAlertEvent> list(Long monitorId, String state) {
    var wrapper = Wrappers.<OpinionAlertEvent>lambdaQuery();
    if (monitorId != null) {
      accessService.requireMonitor(monitorId);
      wrapper.eq(OpinionAlertEvent::getMonitorId, monitorId);
    } else if (OpinionCurrentUser.isAuthenticated() && !OpinionCurrentUser.isAdmin()) {
      var ids = accessService.visibleMonitorIds();
      if (ids.isEmpty()) {
        return List.of();
      }
      wrapper.in(OpinionAlertEvent::getMonitorId, ids);
    }
    if (state != null && !state.isBlank()) {
      wrapper.eq(OpinionAlertEvent::getState, state);
    }
    return eventMapper.selectList(wrapper.orderByDesc(OpinionAlertEvent::getLastTriggeredAt));
  }

  public OpinionAlertEvent get(Long id) {
    OpinionAlertEvent event = eventMapper.selectById(id);
    if (event == null) {
      throw new IllegalArgumentException("告警事件不存在");
    }
    if (event.getMonitorId() != null) {
      accessService.requireMonitor(event.getMonitorId());
    }
    return event;
  }

  public OpinionAlertEvent handle(Long id, AlertHandleRequest request) {
    OpinionAlertEvent event = get(id);
    String state = request.getState();
    if (!STATES.contains(state)) {
      throw new IllegalArgumentException("非法处置状态：" + state);
    }
    event.setState(state);
    event.setOwner(
        request.getOwner() == null || request.getOwner().isBlank()
            ? OpinionCurrentUser.username()
            : request.getOwner());
    event.setHandleNote(request.getNote());
    event.setUpdatedAt(LocalDateTime.now());
    if ("resolved".equals(state) || "closed".equals(state)) {
      event.setResolvedAt(LocalDateTime.now());
    }
    eventMapper.updateById(event);
    auditService.record(
        "ALERT_HANDLE",
        "opinion_alert_event",
        id,
        Map.of("state", state, "note", request.getNote()),
        null);
    return event;
  }

  public List<OpinionNotification> notifications(Long alertId) {
    if (alertId != null) {
      OpinionAlertEvent alert = get(alertId);
      if (alert.getMonitorId() != null) {
        accessService.requireMonitor(alert.getMonitorId());
      }
    }
    var wrapper = Wrappers.<OpinionNotification>lambdaQuery();
    if (alertId != null) {
      wrapper.eq(OpinionNotification::getAlertId, alertId);
    }
    return notificationMapper.selectList(wrapper.orderByDesc(OpinionNotification::getCreatedAt));
  }
}
