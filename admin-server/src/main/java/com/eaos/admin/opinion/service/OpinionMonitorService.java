package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.dto.OpinionMonitorRequest;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import com.eaos.admin.opinion.mapper.OpinionMonitorMapper;
import com.eaos.admin.opinion.support.OpinionAuditService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

@Service
@RequiredArgsConstructor
public class OpinionMonitorService {

  private final OpinionMonitorMapper monitorMapper;
  private final OpinionAuditService auditService;

  public List<OpinionMonitor> list() {
    LambdaQueryWrapper<OpinionMonitor> wrapper = Wrappers.lambdaQuery();
    if (OpinionCurrentUser.isAuthenticated() && !OpinionCurrentUser.isAdmin()) {
      wrapper.eq(OpinionMonitor::getUserId, OpinionCurrentUser.id());
    }
    return monitorMapper.selectList(wrapper.orderByDesc(OpinionMonitor::getCreatedAt));
  }

  public OpinionMonitor get(Long id) {
    OpinionMonitor monitor = monitorMapper.selectById(id);
    if (monitor == null) {
      throw new IllegalArgumentException("监控任务不存在");
    }
    checkOwnership(monitor);
    return monitor;
  }

  public OpinionMonitor create(OpinionMonitorRequest request) {
    OpinionMonitor monitor = new OpinionMonitor();
    apply(monitor, request);
    monitor.setUserId(OpinionCurrentUser.id());
    monitorMapper.insert(monitor);
    auditService.record(
        "MONITOR_CREATE",
        "opinion_monitor",
        monitor.getId(),
        Map.of("name", monitor.getName()),
        null);
    return monitor;
  }

  public OpinionMonitor update(Long id, OpinionMonitorRequest request) {
    OpinionMonitor monitor = get(id);
    apply(monitor, request);
    monitor.setUpdatedAt(LocalDateTime.now());
    monitorMapper.updateById(monitor);
    auditService.record(
        "MONITOR_UPDATE", "opinion_monitor", id, Map.of("name", monitor.getName()), null);
    return monitor;
  }

  public void delete(Long id) {
    OpinionMonitor monitor = get(id);
    if (!OpinionCurrentUser.isAdmin()) {
      throw new IllegalArgumentException("仅管理员可删除监控任务");
    }
    monitorMapper.deleteById(id);
    auditService.record(
        "MONITOR_DELETE", "opinion_monitor", id, Map.of("name", monitor.getName()), null);
  }

  public OpinionMonitor toggle(Long id) {
    OpinionMonitor monitor = get(id);
    monitor.setStatus("enabled".equalsIgnoreCase(monitor.getStatus()) ? "disabled" : "enabled");
    monitor.setUpdatedAt(LocalDateTime.now());
    monitorMapper.updateById(monitor);
    return monitor;
  }

  private void apply(OpinionMonitor monitor, OpinionMonitorRequest request) {
    monitor.setName(request.getName().trim());
    monitor.setEnterpriseName(nullToEmpty(request.getEnterpriseName()));
    monitor.setBrandWords(orEmpty(request.getBrandWords()));
    monitor.setCompetitorWords(orEmpty(request.getCompetitorWords()));
    monitor.setExecutiveNames(orEmpty(request.getExecutiveNames()));
    monitor.setExcludeWords(orEmpty(request.getExcludeWords()));
    monitor.setMatchMode(request.getMatchMode() == null ? "any" : request.getMatchMode());
    monitor.setTimeWindowDays(
        request.getTimeWindowDays() == null ? 7 : request.getTimeWindowDays());
    monitor.setStatus(request.getStatus() == null ? "enabled" : request.getStatus());
  }

  private void checkOwnership(OpinionMonitor monitor) {
    if (OpinionCurrentUser.isAuthenticated()
        && !OpinionCurrentUser.isAdmin()
        && !java.util.Objects.equals(monitor.getUserId(), OpinionCurrentUser.id())) {
      throw new IllegalArgumentException("无权访问该监控任务");
    }
  }

  private static String nullToEmpty(String value) {
    return value == null ? "" : value.trim();
  }

  private static List<String> orEmpty(List<String> value) {
    return value == null ? List.of() : value;
  }
}
