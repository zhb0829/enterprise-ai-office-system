package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.opinion.config.OpinionServiceProperties;
import com.eaos.admin.opinion.entity.OpinionAlertEvent;
import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionArticle;
import com.eaos.admin.opinion.entity.OpinionEvent;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import com.eaos.admin.opinion.entity.OpinionReport;
import com.eaos.admin.opinion.mapper.OpinionAlertEventMapper;
import com.eaos.admin.opinion.mapper.OpinionAnalysisMapper;
import com.eaos.admin.opinion.mapper.OpinionArticleMapper;
import com.eaos.admin.opinion.mapper.OpinionEventMapper;
import com.eaos.admin.opinion.mapper.OpinionMonitorMapper;
import com.eaos.admin.opinion.mapper.OpinionReportMapper;
import com.eaos.admin.opinion.support.InternalTokenVerifier;
import com.eaos.admin.opinion.support.OpinionAccessService;
import com.eaos.admin.opinion.support.OpinionAuditService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import com.eaos.admin.opinion.support.OpinionHtmlSanitizer;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

@Slf4j
@Service
@RequiredArgsConstructor
public class OpinionReportService {

  private final OpinionReportMapper reportMapper;
  private final OpinionMonitorMapper monitorMapper;
  private final OpinionArticleMapper articleMapper;
  private final OpinionAnalysisMapper analysisMapper;
  private final OpinionEventMapper eventMapper;
  private final OpinionAlertEventMapper alertEventMapper;
  private final RestTemplate restTemplate;
  private final AiServiceProperties aiProperties;
  private final OpinionServiceProperties opinionProperties;
  private final OpinionAuditService auditService;
  private final OpinionAccessService accessService;

  /** 生成报告（正文由 Python LLM 生成，Java 保存元数据并作为权威版本）。 */
  @Transactional
  public OpinionReport generate(Long monitorId, String period) {
    accessService.requireMonitor(monitorId);
    OpinionMonitor monitor = monitorMapper.selectByIdForUpdate(monitorId);
    if (monitor == null) {
      throw new IllegalArgumentException("监控任务不存在");
    }
    period = period == null || period.isBlank() ? "daily" : period;
    LocalDateTime end = LocalDateTime.now();
    LocalDateTime start = "weekly".equals(period) ? end.minusDays(7) : end.minusDays(1);

    Map<String, Object> data = buildData(monitor, start, end);
    Map<String, Object> generated = callPythonReport(monitorId, period, start, end, data);

    int nextVersion = nextVersion(monitorId, period);
    OpinionReport report = new OpinionReport();
    report.setMonitorId(monitorId);
    report.setPeriod(period);
    report.setPeriodStart(start);
    report.setPeriodEnd(end);
    report.setTitle("舆情" + ("weekly".equals(period) ? "周报" : "日报") + "（" + monitor.getName() + "）");
    report.setSummary(String.valueOf(generated.getOrDefault("summary", "")));
    report.setContentHtml(
        OpinionHtmlSanitizer.clean(String.valueOf(generated.getOrDefault("contentHtml", ""))));
    report.setStatus("draft");
    report.setVersion(nextVersion);
    report.setModel(String.valueOf(generated.getOrDefault("model", "")));
    report.setPromptVersion(String.valueOf(generated.getOrDefault("promptVersion", "")));
    report.setDataScope(
        Map.of("period", period, "start", String.valueOf(start), "end", String.valueOf(end)));
    report.setEvidence(castList(generated.get("evidence")));
    reportMapper.insert(report);
    auditService.record(
        "REPORT_GENERATE",
        "opinion_report",
        report.getId(),
        Map.of("monitorId", monitorId, "period", period, "version", nextVersion),
        null);
    return report;
  }

  /** 人工确认后发布（不可覆盖，重新生成产生新版本）。 */
  @Transactional
  public OpinionReport publish(Long id) {
    OpinionReport report = reportMapper.selectById(id);
    if (report == null) {
      throw new IllegalArgumentException("报告不存在");
    }
    if (report.getMonitorId() != null) {
      accessService.requireMonitor(report.getMonitorId());
    }
    report.setStatus("published");
    report.setPublishedBy(OpinionCurrentUser.username());
    report.setPublishedAt(LocalDateTime.now());
    report.setUpdatedAt(LocalDateTime.now());
    reportMapper.updateById(report);
    auditService.record(
        "REPORT_PUBLISH", "opinion_report", id, Map.of("version", report.getVersion()), null);
    return report;
  }

  public List<OpinionReport> list(Long monitorId, String period) {
    var wrapper = Wrappers.<OpinionReport>lambdaQuery();
    if (monitorId != null) {
      accessService.requireMonitor(monitorId);
      wrapper.eq(OpinionReport::getMonitorId, monitorId);
    } else if (OpinionCurrentUser.isAuthenticated() && !OpinionCurrentUser.isAdmin()) {
      var ids = accessService.visibleMonitorIds();
      if (ids.isEmpty()) {
        return List.of();
      }
      wrapper.in(OpinionReport::getMonitorId, ids);
    }
    if (period != null && !period.isBlank()) {
      wrapper.eq(OpinionReport::getPeriod, period);
    }
    return reportMapper.selectList(
        wrapper.orderByDesc(OpinionReport::getCreatedAt).orderByDesc(OpinionReport::getVersion));
  }

  public OpinionReport get(Long id) {
    OpinionReport report = reportMapper.selectById(id);
    if (report == null) {
      throw new IllegalArgumentException("报告不存在");
    }
    if (report.getMonitorId() != null) {
      accessService.requireMonitor(report.getMonitorId());
    }
    return report;
  }

  public Map<String, Object> exportPdf(Long id) {
    OpinionReport report = get(id);
    String base = aiProperties.getBaseUrl();
    String url = base + "/internal/opinion/reports/pdf";
    HttpHeaders headers = internalHeaders();
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("reportId", id);
    body.put("title", report.getTitle());
    body.put("contentHtml", report.getContentHtml());
    HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
    try {
      @SuppressWarnings("unchecked")
      Map<String, Object> response = restTemplate.postForObject(url, entity, Map.class);
      return response == null ? Map.of("downloadUrl", "") : response;
    } catch (Exception e) {
      log.warn("报告 PDF 导出失败 reportId={}: {}", id, e.getMessage());
      return Map.of("downloadUrl", "", "error", e.getMessage());
    }
  }

  private int nextVersion(Long monitorId, String period) {
    OpinionReport latest = reportMapper.selectLatestForUpdate(monitorId, period);
    return latest == null || latest.getVersion() == null ? 1 : latest.getVersion() + 1;
  }

  private Map<String, Object> buildData(
      OpinionMonitor monitor, LocalDateTime start, LocalDateTime end) {
    List<OpinionArticle> articles =
        articleMapper.selectList(
            Wrappers.<OpinionArticle>lambdaQuery()
                .eq(OpinionArticle::getMonitorId, monitor.getId())
                .ge(OpinionArticle::getCollectedAt, start)
                .le(OpinionArticle::getCollectedAt, end));
    List<Long> ids = articles.stream().map(OpinionArticle::getId).toList();
    List<OpinionAnalysis> analyses =
        ids.isEmpty()
            ? List.of()
            : analysisMapper.selectList(
                Wrappers.<OpinionAnalysis>lambdaQuery().in(OpinionAnalysis::getArticleId, ids));
    int positive = 0;
    int neutral = 0;
    int negative = 0;
    for (OpinionAnalysis analysis : analyses) {
      switch (analysis.getSentiment()) {
        case "positive" -> positive++;
        case "negative" -> negative++;
        default -> neutral++;
      }
    }
    List<OpinionEvent> events =
        eventMapper.selectList(
            Wrappers.<OpinionEvent>lambdaQuery()
                .eq(OpinionEvent::getMonitorId, monitor.getId())
                .orderByDesc(OpinionEvent::getReportCount)
                .last("LIMIT 10"));
    List<OpinionAlertEvent> alerts =
        alertEventMapper.selectList(
            Wrappers.<OpinionAlertEvent>lambdaQuery()
                .eq(OpinionAlertEvent::getMonitorId, monitor.getId())
                .ge(OpinionAlertEvent::getLastTriggeredAt, start)
                .orderByDesc(OpinionAlertEvent::getLastTriggeredAt)
                .last("LIMIT 10"));

    List<Map<String, Object>> eventItems = new ArrayList<>();
    for (OpinionEvent event : events) {
      Map<String, Object> item = new LinkedHashMap<>();
      item.put("title", event.getTitle());
      item.put("riskLevel", event.getRiskLevel());
      item.put("reportCount", event.getReportCount());
      item.put("sentimentDist", event.getSentimentDist());
      item.put("summary", event.getSummary());
      eventItems.add(item);
    }
    List<Map<String, Object>> alertItems = new ArrayList<>();
    for (OpinionAlertEvent alert : alerts) {
      Map<String, Object> item = new LinkedHashMap<>();
      item.put("riskLevel", alert.getRiskLevel());
      item.put("state", alert.getState());
      item.put("triggerCount", alert.getTriggerCount());
      item.put("lastTriggeredAt", String.valueOf(alert.getLastTriggeredAt()));
      alertItems.add(item);
    }
    List<Map<String, Object>> evidenceItems = new ArrayList<>();
    for (OpinionArticle article : articles) {
      if (evidenceItems.size() >= 12) {
        break;
      }
      Map<String, Object> item = new LinkedHashMap<>();
      item.put("type", "article");
      item.put("title", article.getTitle());
      item.put("url", article.getUrl());
      item.put("time", String.valueOf(article.getCollectedAt()));
      evidenceItems.add(item);
    }

    Map<String, Object> data = new LinkedHashMap<>();
    data.put("monitor", monitor.getName());
    data.put("brandWords", monitor.getBrandWords());
    data.put("articleCount", articles.size());
    data.put("sentiment", Map.of("positive", positive, "neutral", neutral, "negative", negative));
    data.put("events", eventItems);
    data.put("alerts", alertItems);
    data.put("evidence", evidenceItems);
    return data;
  }

  private Map<String, Object> callPythonReport(
      Long monitorId,
      String period,
      LocalDateTime start,
      LocalDateTime end,
      Map<String, Object> data) {
    String base = aiProperties.getBaseUrl();
    String url = base + "/internal/opinion/reports/generate";
    HttpHeaders headers = internalHeaders();
    Map<String, Object> body = new LinkedHashMap<>();
    body.put("monitorId", monitorId);
    body.put("period", period);
    body.put("periodStart", String.valueOf(start));
    body.put("periodEnd", String.valueOf(end));
    body.put("data", data);
    try {
      @SuppressWarnings("unchecked")
      Map<String, Object> response =
          restTemplate.postForObject(url, new HttpEntity<>(body, headers), Map.class);
      if (response == null) {
        throw new IllegalArgumentException("报告生成接口无返回");
      }
      return response;
    } catch (Exception e) {
      log.error("报告生成失败 monitorId={}: {}", monitorId, e.getMessage());
      throw new IllegalArgumentException("报告生成失败：" + e.getMessage());
    }
  }

  private HttpHeaders internalHeaders() {
    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    headers.set(InternalTokenVerifier.HEADER, opinionProperties.getInternalToken());
    return headers;
  }

  @SuppressWarnings("unchecked")
  private List<Object> castList(Object value) {
    return value instanceof List ? (List<Object>) value : List.of();
  }
}
