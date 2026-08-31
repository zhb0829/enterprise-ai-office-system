package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.entity.OpinionAlertEvent;
import com.eaos.admin.opinion.entity.OpinionAlertRule;
import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionArticle;
import com.eaos.admin.opinion.entity.OpinionEvent;
import com.eaos.admin.opinion.mapper.OpinionAlertEventMapper;
import com.eaos.admin.opinion.mapper.OpinionAlertRuleMapper;
import com.eaos.admin.opinion.mapper.OpinionAnalysisMapper;
import com.eaos.admin.opinion.mapper.OpinionArticleMapper;
import com.eaos.admin.opinion.mapper.OpinionEventMapper;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

@Slf4j
@Service
@RequiredArgsConstructor
public class OpinionAlertEngine {

  private static final List<String> SEVERITY = List.of("关注", "预警", "危机");

  private final OpinionAlertRuleMapper ruleMapper;
  private final OpinionAlertEventMapper eventMapper;
  private final OpinionArticleMapper articleMapper;
  private final OpinionAnalysisMapper analysisMapper;
  private final OpinionEventMapper eventMapper2;
  private final OpinionNotificationService notificationService;

  /** 采集/分析落地后评估某监控任务，命中规则则触发/合并告警。 */
  public void evaluate(Long monitorId) {
    if (monitorId == null) {
      return;
    }
    List<OpinionAlertRule> rules =
        ruleMapper.selectList(
            Wrappers.<OpinionAlertRule>lambdaQuery()
                .eq(OpinionAlertRule::getMonitorId, monitorId)
                .eq(OpinionAlertRule::getStatus, "enabled"));
    if (rules.isEmpty()) {
      return;
    }
    for (OpinionAlertRule rule : rules) {
      int windowHours = intValue(rule.getTrigger(), "windowHours", 24);
      Map<String, Object> stats = computeStats(monitorId, windowHours);
      if (!ruleMatches(rule, stats)) {
        continue;
      }
      String level = escalateLevel(rule, stats);
      boolean notify = notificationDue(rule);
      OpinionAlertEvent alert = upsertAlert(rule, stats, level);
      if (notify) {
        notificationService.notifyAlert(alert, monitorId, stats);
      }
    }
  }

  private Map<String, Object> computeStats(Long monitorId, int windowHours) {
    LocalDateTime now = LocalDateTime.now();
    LocalDateTime cutoff = now.minusHours(Math.max(1, windowHours));
    List<OpinionArticle> articles =
        articleMapper.selectList(
            Wrappers.<OpinionArticle>lambdaQuery()
                .eq(OpinionArticle::getMonitorId, monitorId)
                .ge(OpinionArticle::getCollectedAt, cutoff)
                .eq(OpinionArticle::getStatus, "analyzed"));
    if (articles.isEmpty()) {
      return baseStats();
    }
    Set<Long> ids = articles.stream().map(OpinionArticle::getId).collect(Collectors.toSet());
    List<OpinionAnalysis> analyses =
        analysisMapper.selectList(
            Wrappers.<OpinionAnalysis>lambdaQuery().in(OpinionAnalysis::getArticleId, ids));
    Map<Long, OpinionAnalysis> latest = new LinkedHashMap<>();
    for (OpinionAnalysis analysis : analyses) {
      latest.putIfAbsent(analysis.getArticleId(), analysis);
    }
    long negative =
        latest.values().stream().filter(a -> "negative".equals(a.getSentiment())).count();
    long total = latest.size();

    LocalDateTime prevCutoff = cutoff.minusHours(Math.max(1, windowHours));
    List<OpinionArticle> prevArticles =
        articleMapper.selectList(
            Wrappers.<OpinionArticle>lambdaQuery()
                .eq(OpinionArticle::getMonitorId, monitorId)
                .ge(OpinionArticle::getCollectedAt, prevCutoff)
                .lt(OpinionArticle::getCollectedAt, cutoff)
                .eq(OpinionArticle::getStatus, "analyzed"));
    Set<Long> prevIds =
        prevArticles.stream().map(OpinionArticle::getId).collect(Collectors.toSet());
    List<OpinionAnalysis> prevAnalyses =
        prevIds.isEmpty()
            ? List.of()
            : analysisMapper.selectList(
                Wrappers.<OpinionAnalysis>lambdaQuery().in(OpinionAnalysis::getArticleId, prevIds));
    Map<Long, OpinionAnalysis> prevLatest = new LinkedHashMap<>();
    for (OpinionAnalysis analysis : prevAnalyses) {
      prevLatest.putIfAbsent(analysis.getArticleId(), analysis);
    }
    long prevNegative =
        prevLatest.values().stream().filter(a -> "negative".equals(a.getSentiment())).count();

    long sourceCount =
        articles.stream()
            .map(OpinionArticle::getSourceId)
            .filter(java.util.Objects::nonNull)
            .distinct()
            .count();
    double growth =
        prevNegative <= 0
            ? (negative > 0 ? 1.0 : 0.0)
            : (double) (negative - prevNegative) / prevNegative;

    List<OpinionEvent> events =
        eventMapper2.selectList(
            Wrappers.<OpinionEvent>lambdaQuery().eq(OpinionEvent::getMonitorId, monitorId));
    int spreadSpeed =
        events.stream()
            .mapToInt(e -> e.getSpreadSpeed() == null ? 0 : e.getSpreadSpeed())
            .max()
            .orElse(0);

    Map<String, Object> stats = new LinkedHashMap<>();
    stats.put("negativeCount", negative);
    stats.put("totalCount", total);
    stats.put("negativeRatio", total == 0 ? 0.0 : Math.round(negative * 1000.0 / total) / 1000.0);
    stats.put("growthRate", Math.round(growth * 1000.0) / 1000.0);
    stats.put("sourceCount", sourceCount);
    stats.put("spreadSpeed", spreadSpeed);
    return stats;
  }

  private Map<String, Object> baseStats() {
    Map<String, Object> stats = new LinkedHashMap<>();
    stats.put("negativeCount", 0L);
    stats.put("totalCount", 0L);
    stats.put("negativeRatio", 0.0);
    stats.put("growthRate", 0.0);
    stats.put("sourceCount", 0L);
    stats.put("spreadSpeed", 0);
    return stats;
  }

  /** OR 语义：任一条件命中即触发。 */
  private boolean ruleMatches(OpinionAlertRule rule, Map<String, Object> stats) {
    Map<String, Object> trigger = rule.getTrigger();
    if (trigger == null || trigger.isEmpty()) {
      return false;
    }
    if (ge(stats.get("negativeCount"), trigger.get("negativeCount"))
        || ge(stats.get("negativeRatio"), trigger.get("negativeRatio"))
        || ge(stats.get("growthRate"), trigger.get("growthRate"))
        || ge(stats.get("sourceCount"), trigger.get("sourceCount"))
        || ge(stats.get("spreadSpeed"), trigger.get("spreadSpeed"))) {
      return true;
    }
    return false;
  }

  /** 升级：规则等级 与 统计推断等级 取更高。 */
  private String escalateLevel(OpinionAlertRule rule, Map<String, Object> stats) {
    String inferred = "关注";
    Map<String, Object> escalate = rule.getEscalate();
    if (escalate != null && !escalate.isEmpty()) {
      long neg = ((Number) stats.getOrDefault("negativeCount", 0L)).longValue();
      double ratio = ((Number) stats.getOrDefault("negativeRatio", 0.0)).doubleValue();
      if (ge(neg, escalate.get("crisisCount")) || ge(ratio, escalate.get("crisisRatio"))) {
        inferred = "危机";
      } else if (ge(neg, escalate.get("warningCount")) || ge(ratio, escalate.get("warningRatio"))) {
        inferred = "预警";
      }
    }
    return severityMax(rule.getRiskLevel(), inferred);
  }

  private OpinionAlertEvent upsertAlert(
      OpinionAlertRule rule, Map<String, Object> stats, String level) {
    LocalDateTime now = LocalDateTime.now();
    OpinionAlertEvent latest =
        eventMapper.selectOne(
            Wrappers.<OpinionAlertEvent>lambdaQuery()
                .eq(OpinionAlertEvent::getMonitorId, rule.getMonitorId())
                .eq(OpinionAlertEvent::getRuleId, rule.getId())
                .orderByDesc(OpinionAlertEvent::getLastTriggeredAt)
                .last("LIMIT 1"));
    int cooldown = rule.getCooldownMinutes() == null ? 60 : rule.getCooldownMinutes();
    if (latest != null
        && java.time.Duration.between(latest.getLastTriggeredAt(), now).toMinutes() <= cooldown) {
      latest.setTriggerCount((latest.getTriggerCount() == null ? 1 : latest.getTriggerCount()) + 1);
      latest.setTriggerStats(stats);
      latest.setRiskLevel(severityMax(latest.getRiskLevel(), level));
      if ("resolved".equals(latest.getState()) || "closed".equals(latest.getState())) {
        latest.setState("triggered");
      }
      latest.setUpdatedAt(now);
      eventMapper.updateById(latest);
      return latest;
    }
    OpinionAlertEvent event = new OpinionAlertEvent();
    event.setMonitorId(rule.getMonitorId());
    event.setRuleId(rule.getId());
    event.setRiskLevel(level);
    event.setState("triggered");
    event.setTriggerStats(stats);
    event.setTriggerCount(1);
    event.setFirstTriggeredAt(now);
    event.setLastTriggeredAt(now);
    eventMapper.insert(event);
    return event;
  }

  private boolean notificationDue(OpinionAlertRule rule) {
    OpinionAlertEvent latest =
        eventMapper.selectOne(
            Wrappers.<OpinionAlertEvent>lambdaQuery()
                .eq(OpinionAlertEvent::getMonitorId, rule.getMonitorId())
                .eq(OpinionAlertEvent::getRuleId, rule.getId())
                .orderByDesc(OpinionAlertEvent::getLastTriggeredAt)
                .last("LIMIT 1"));
    if (latest == null || latest.getLastTriggeredAt() == null) {
      return true;
    }
    int cooldown = rule.getCooldownMinutes() == null ? 60 : rule.getCooldownMinutes();
    return java.time.Duration.between(latest.getLastTriggeredAt(), LocalDateTime.now()).toMinutes()
        > cooldown;
  }

  private boolean ge(Object left, Object right) {
    if (right == null) {
      return false;
    }
    try {
      return ((Number) left).doubleValue() >= ((Number) right).doubleValue();
    } catch (Exception e) {
      return false;
    }
  }

  private int intValue(Map<String, Object> map, String key, int defaultValue) {
    Object value = map.get(key);
    if (value instanceof Number) {
      return ((Number) value).intValue();
    }
    return defaultValue;
  }

  private String severityMax(String left, String right) {
    int li = left == null ? 0 : Math.max(0, SEVERITY.indexOf(left));
    int ri = right == null ? 0 : Math.max(0, SEVERITY.indexOf(right));
    return SEVERITY.get(Math.max(li, ri));
  }
}
