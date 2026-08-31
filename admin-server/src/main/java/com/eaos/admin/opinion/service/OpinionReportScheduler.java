package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.config.OpinionServiceProperties;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import com.eaos.admin.opinion.mapper.OpinionMonitorMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class OpinionReportScheduler {

  private final OpinionMonitorMapper monitorMapper;
  private final OpinionReportService reportService;
  private final OpinionServiceProperties properties;

  @Scheduled(cron = "${OPINION_DAILY_REPORT_CRON:0 10 7 * * *}")
  public void generateDailyReports() {
    if (!properties.isAutoReportEnabled()) {
      return;
    }
    monitorMapper
        .selectList(Wrappers.<OpinionMonitor>lambdaQuery().eq(OpinionMonitor::getStatus, "enabled"))
        .forEach(monitor -> generate(monitor, "daily"));
  }

  @Scheduled(cron = "${OPINION_WEEKLY_REPORT_CRON:0 20 7 * * MON}")
  public void generateWeeklyReports() {
    if (!properties.isAutoReportEnabled()) {
      return;
    }
    monitorMapper
        .selectList(Wrappers.<OpinionMonitor>lambdaQuery().eq(OpinionMonitor::getStatus, "enabled"))
        .forEach(monitor -> generate(monitor, "weekly"));
  }

  private void generate(OpinionMonitor monitor, String period) {
    try {
      reportService.generate(monitor.getId(), period);
    } catch (Exception e) {
      log.warn("auto {} report failed monitorId={}: {}", period, monitor.getId(), e.getMessage());
    }
  }
}
