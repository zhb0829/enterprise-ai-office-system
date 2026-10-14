package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionArticle;
import com.eaos.admin.opinion.entity.OpinionEvent;
import com.eaos.admin.opinion.mapper.OpinionAnalysisMapper;
import com.eaos.admin.opinion.mapper.OpinionArticleMapper;
import com.eaos.admin.opinion.mapper.OpinionEventMapper;
import com.eaos.admin.opinion.support.OpinionAccessService;
import com.eaos.admin.opinion.support.OpinionRiskModel;
import com.eaos.admin.opinion.support.OpinionTrendModel;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.DayOfWeek;
import java.time.LocalDateTime;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class OpinionEventService {

  private final OpinionEventMapper eventMapper;
  private final OpinionAnalysisMapper analysisMapper;
  private final OpinionArticleMapper articleMapper;
  private final OpinionAccessService accessService;

  /** 主体、类型与周窗口形成稳定事件键，未知主体不跨文章合并。 */
  @Transactional
  public void aggregate(Long monitorId) {
    accessService.requireMonitor(monitorId);
    eventMapper.lockMonitor(monitorId);
    LocalDateTime now = LocalDateTime.now();
    List<OpinionArticle> articles =
        articleMapper.selectList(
            Wrappers.<OpinionArticle>lambdaQuery()
                .eq(OpinionArticle::getMonitorId, monitorId)
                .eq(OpinionArticle::getStatus, "analyzed")
                .orderByAsc(OpinionArticle::getId));
    if (articles.isEmpty()) {
      for (OpinionEvent event : eventMapper.selectList(
          Wrappers.<OpinionEvent>lambdaQuery().eq(OpinionEvent::getMonitorId, monitorId))) {
        event.setStatus("superseded");
        eventMapper.updateById(event);
      }
      return;
    }
    List<Long> ids = articles.stream().map(OpinionArticle::getId).toList();
    List<OpinionAnalysis> analyses =
        analysisMapper.selectList(
            Wrappers.<OpinionAnalysis>lambdaQuery()
                .in(OpinionAnalysis::getArticleId, ids)
                .eq(OpinionAnalysis::getMonitorId, monitorId)
                .orderByDesc(OpinionAnalysis::getVersion).orderByDesc(OpinionAnalysis::getId));
    Map<Long, OpinionAnalysis> latest = new LinkedHashMap<>();
    for (OpinionAnalysis analysis : analyses) {
      latest.putIfAbsent(analysis.getArticleId(), analysis);
    }

    Map<String, Set<Long>> groups = new LinkedHashMap<>();
    for (OpinionArticle article : articles) {
      OpinionAnalysis analysis = latest.get(article.getId());
      if (analysis == null || "rejected".equals(analysis.getStatus())) continue;
      String subject = analysis.getSubjects() == null || analysis.getSubjects().isEmpty()
          ? "unidentified:" + article.getId() : analysis.getSubjects().stream().sorted().findFirst().orElse("");
      var week = OpinionTrendModel.articleTime(article, now).toLocalDate()
          .with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
      String key = hash(monitorId + "\n" + subject + "\n" + analysis.getEventType() + "\n" + week);
      groups.computeIfAbsent(key, k -> new LinkedHashSet<>()).add(article.getId());
    }

    for (OpinionEvent event : eventMapper.selectList(
        Wrappers.<OpinionEvent>lambdaQuery().eq(OpinionEvent::getMonitorId, monitorId))) {
      if (!groups.containsKey(event.getEventKey())) {
        event.setStatus("superseded");
        event.setUpdatedAt(now);
        eventMapper.updateById(event);
      }
    }
    for (Map.Entry<String, Set<Long>> entry : groups.entrySet()) {
      String eventKey = entry.getKey();
      Set<Long> articleIds = entry.getValue();
      OpinionEvent event =
          eventMapper.selectOne(
              Wrappers.<OpinionEvent>lambdaQuery()
                  .eq(OpinionEvent::getMonitorId, monitorId)
                  .eq(OpinionEvent::getEventKey, eventKey));
      if (event == null) {
        event = new OpinionEvent();
        event.setMonitorId(monitorId);
        event.setEventKey(eventKey);
        event.setStatus("active");
        event.setVersion(1);
      } else {
        event.setVersion((event.getVersion() == null ? 0 : event.getVersion()) + 1);
      }
      List<OpinionArticle> rows = articles.stream().filter(a -> articleIds.contains(a.getId())).toList();
      List<OpinionArticle> sorted = new ArrayList<>(rows);
      sorted.sort((a, b) -> OpinionTrendModel.articleTime(a, now).compareTo(OpinionTrendModel.articleTime(b, now)));

      LocalDateTime start = sorted.isEmpty() ? now : OpinionTrendModel.articleTime(sorted.get(0), now);
      LocalDateTime end =
          sorted.isEmpty() ? now : OpinionTrendModel.articleTime(sorted.get(rows.size() - 1), now);
      int positive = 0;
      int neutral = 0;
      int negative = 0;
      Set<String> sources = new LinkedHashSet<>();
      List<String> keywords = new ArrayList<>();
      List<Long> newArticleIds = new ArrayList<>(articleIds);
      for (OpinionArticle row : sorted) {
        OpinionAnalysis analysis = latest.get(row.getId());
        if (analysis == null) {
          neutral++;
          continue;
        }
        switch (analysis.getSentiment()) {
          case "positive" -> positive++;
          case "negative" -> negative++;
          default -> neutral++;
        }
        if (row.getSourceId() != null) {
          sources.add(String.valueOf(row.getSourceId()));
        }
        if (analysis.getKeywords() != null) {
          keywords.addAll(analysis.getKeywords());
        }
      }
      event.setArticleIds(newArticleIds);
      event.setSentimentDist(
          Map.of("positive", positive, "neutral", neutral, "negative", negative));
      event.setReportCount(rows.size());
      event.setTimeStart(start);
      event.setTimeEnd(end);
      event.setSourceWeight(new BigDecimal(sources.size()));
      var trend = OpinionTrendModel.calculate(rows, latest, now);
      var risk = OpinionRiskModel.calculate(rows.stream().map(a -> latest.get(a.getId())).toList(), trend);
      var subjects = rows.stream().map(a -> latest.get(a.getId())).flatMap(a ->
          (a.getSubjects() == null ? List.<String>of() : a.getSubjects()).stream()).distinct().sorted().toList();
      event.setSubjects(subjects);
      String type = latest.get(sorted.get(0).getId()).getEventType();
      event.setEventType(type == null ? "other" : type);
      String title = subjects.isEmpty() ? sorted.get(0).getTitle() : String.join("、", subjects) + " · " + event.getEventType();
      if (title == null || title.isBlank()) title = "未命名事件";
      event.setTitle(title.substring(0, Math.min(256, title.length())));
      event.setSpreadSpeed(trend.currentCount());
      event.setReportsPerHour(BigDecimal.valueOf(trend.reportsPerHour()));
      event.setTrendDirection(trend.direction());
      event.setGrowthRate(trend.growthRate() == null ? null : BigDecimal.valueOf(trend.growthRate()));
      event.setTimeline(trend.timeline());
      event.setRiskScore(risk.score());
      event.setRiskFactors(risk.factors());
      event.setRiskModelVersion(OpinionRiskModel.VERSION);
      event.setReviewRequired(risk.reviewRequired());
      event.setKeywords(keywords.stream().distinct().limit(10).toList());
      event.setRiskLevel(risk.level());
      event.setSummary("共聚合 " + rows.size() + " 篇相关文章，来源 " + sources.size() + " 个。");
      event.setUpdatedAt(LocalDateTime.now());
      event.setStatus("active");
      if (event.getId() == null) {
        eventMapper.insert(event);
      } else {
        eventMapper.updateById(event);
      }
    }
  }

  private static String hash(String value) {
    try {
      return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }

  public List<OpinionEvent> list(Long monitorId, String riskLevel) {
    var wrapper = Wrappers.<OpinionEvent>lambdaQuery().eq(OpinionEvent::getStatus, "active");
    if (monitorId != null) {
      accessService.requireMonitor(monitorId);
      wrapper.eq(OpinionEvent::getMonitorId, monitorId);
    } else if (com.eaos.admin.opinion.support.OpinionCurrentUser.isAuthenticated()
        && !com.eaos.admin.opinion.support.OpinionCurrentUser.isAdmin()) {
      var ids = accessService.visibleMonitorIds();
      if (ids.isEmpty()) {
        return List.of();
      }
      wrapper.in(OpinionEvent::getMonitorId, ids);
    }
    if (riskLevel != null && !riskLevel.isBlank()) {
      wrapper.eq(OpinionEvent::getRiskLevel, riskLevel);
    }
    return eventMapper.selectList(
        wrapper.orderByDesc(OpinionEvent::getRiskScore).orderByDesc(OpinionEvent::getReportCount));
  }
}
