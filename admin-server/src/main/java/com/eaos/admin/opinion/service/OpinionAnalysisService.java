package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.config.OpinionServiceProperties;
import com.eaos.admin.opinion.dto.AnalysisResultRequest;
import com.eaos.admin.opinion.dto.ReviewRequest;
import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionAnalysisTask;
import com.eaos.admin.opinion.entity.OpinionArticle;
import com.eaos.admin.opinion.entity.OpinionReview;
import com.eaos.admin.opinion.mapper.OpinionAnalysisMapper;
import com.eaos.admin.opinion.mapper.OpinionAnalysisTaskMapper;
import com.eaos.admin.opinion.mapper.OpinionArticleMapper;
import com.eaos.admin.opinion.mapper.OpinionReviewMapper;
import com.eaos.admin.opinion.support.OpinionAccessService;
import com.eaos.admin.opinion.support.OpinionAuditService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import com.eaos.admin.opinion.support.OpinionText;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class OpinionAnalysisService {

  private final OpinionAnalysisTaskMapper taskMapper;
  private final OpinionAnalysisMapper analysisMapper;
  private final OpinionArticleMapper articleMapper;
  private final OpinionReviewMapper reviewMapper;
  private final OpinionAuditService auditService;
  private final OpinionEventService eventService;
  private final OpinionAlertEngine alertEngine;
  private final OpinionServiceProperties properties;
  private final OpinionAccessService accessService;

  @Transactional
  public Map<String, Object> claimNext(String worker) {
    OpinionAnalysisTask task =
        taskMapper.claimNext(
            worker == null || worker.isBlank() ? "python-worker" : worker.trim(),
            LocalDateTime.now().minusMinutes(Math.max(1, properties.getStaleTaskMinutes())),
            Math.max(1, properties.getMaxAnalysisRetries()));
    if (task == null) {
      return null;
    }
    OpinionArticle article = articleMapper.selectById(task.getArticleId());
    if (article == null) {
      failTask(task.getId(), "article not found");
      return null;
    }
    String content = article.getContent() == null ? "" : article.getContent();
    Map<String, Object> payload = new LinkedHashMap<>();
    payload.put("taskId", task.getId());
    payload.put("articleId", article.getId());
    payload.put("monitorId", task.getMonitorId());
    payload.put("title", article.getTitle());
    payload.put("content", content.length() > 12000 ? content.substring(0, 12000) : content);
    payload.put("url", article.getUrl());
    payload.put(
        "matchedKeywords",
        article.getMatchedKeywords() == null ? List.of() : article.getMatchedKeywords());
    return payload;
  }

  @Transactional
  public void failTask(Long taskId, String error) {
    OpinionAnalysisTask task = taskMapper.selectById(taskId);
    if (task == null || "success".equals(task.getStatus())) {
      return;
    }
    int retryCount = (task.getRetryCount() == null ? 0 : task.getRetryCount()) + 1;
    int maxRetries = Math.max(1, properties.getMaxAnalysisRetries());
    task.setRetryCount(retryCount);
    task.setLastError(OpinionText.trim(error, 4000));
    task.setWorker("");
    task.setClaimedAt(null);
    task.setUpdatedAt(LocalDateTime.now());
    task.setStatus("failed");
    task.setNextRetryAt(
        retryCount >= maxRetries
            ? null
            : LocalDateTime.now().plusMinutes(1L << Math.min(retryCount - 1, 5)));
    taskMapper.updateById(task);
    OpinionArticle article = articleMapper.selectById(task.getArticleId());
    if (article != null) {
      article.setStatus("analysis_failed");
      article.setUpdatedAt(LocalDateTime.now());
      articleMapper.updateById(article);
    }
  }

  @Transactional
  public OpinionAnalysis submitResult(AnalysisResultRequest request) {
    OpinionAnalysisTask task = taskMapper.selectById(request.getTaskId());
    if (task == null) {
      throw new IllegalArgumentException("analysis task not found");
    }
    OpinionArticle article = articleMapper.selectById(request.getArticleId());
    if (article == null) {
      throw new IllegalArgumentException("article not found");
    }
    Long monitorId = request.getMonitorId() == null ? task.getMonitorId() : request.getMonitorId();
    if (!Objects.equals(task.getArticleId(), request.getArticleId())
        || !Objects.equals(task.getMonitorId(), monitorId)) {
      throw new IllegalArgumentException("analysis task does not match article or monitor");
    }

    OpinionAnalysis result = null;
    if (request.getAiRunId() != null && !request.getAiRunId().isBlank()) {
      result =
          analysisMapper.selectOne(
              Wrappers.<OpinionAnalysis>lambdaQuery()
                  .eq(OpinionAnalysis::getArticleId, request.getArticleId())
                  .eq(OpinionAnalysis::getMonitorId, monitorId)
                  .eq(OpinionAnalysis::getAiRunId, request.getAiRunId())
                  .eq(OpinionAnalysis::getSource, "ai")
                  .last("LIMIT 1"));
    }
    if (result == null) {
      result = new OpinionAnalysis();
      result.setArticleId(request.getArticleId());
      result.setMonitorId(monitorId);
      result.setVersion(nextAnalysisVersion(request.getArticleId(), monitorId));
      result.setSource("ai");
      result.setStatus("pending");
      result.setSentiment(request.getSentiment());
      result.setConfidence(
          request.getConfidence() == null ? BigDecimal.ZERO : request.getConfidence());
      result.setEmotionTags(
          request.getEmotionTags() == null ? List.of() : request.getEmotionTags());
      result.setReason(OpinionText.trim(request.getReason(), 4000));
      result.setEvidenceIds(
          request.getEvidenceIds() == null ? List.of() : request.getEvidenceIds());
      result.setRiskFactors(
          request.getRiskFactors() == null ? List.of() : request.getRiskFactors());
      result.setRiskScore(request.getRiskScore() == null ? 0 : request.getRiskScore());
      result.setTopic(OpinionText.trim(request.getTopic(), 256));
      result.setKeywords(request.getKeywords() == null ? List.of() : request.getKeywords());
      result.setModel(OpinionText.trim(request.getModel(), 128));
      result.setPromptVersion(OpinionText.trim(request.getPromptVersion(), 64));
      result.setAiRunId(OpinionText.trim(request.getAiRunId(), 64));
      analysisMapper.insert(result);
    }

    task.setStatus("success");
    task.setNextRetryAt(null);
    task.setClaimedAt(null);
    task.setWorker("");
    task.setLastError("");
    task.setUpdatedAt(LocalDateTime.now());
    taskMapper.updateById(task);
    article.setStatus("analyzed");
    article.setUpdatedAt(LocalDateTime.now());
    articleMapper.updateById(article);
    if (monitorId != null) {
      eventService.aggregate(monitorId);
      alertEngine.evaluate(monitorId);
    }
    return result;
  }

  @Transactional
  public OpinionAnalysis review(Long analysisId, ReviewRequest request) {
    OpinionAnalysis original = analysisMapper.selectById(analysisId);
    if (original == null) {
      throw new IllegalArgumentException("analysis not found");
    }
    accessService.requireMonitor(original.getMonitorId());
    Map<String, Object> oldValue = snapshot(original);
    OpinionAnalysis revised = copyOf(original);
    if (request.getSentiment() != null) {
      revised.setSentiment(request.getSentiment());
    }
    if (request.getConfidence() != null) {
      revised.setConfidence(request.getConfidence());
    }
    if (request.getEmotionTags() != null && !request.getEmotionTags().isEmpty()) {
      revised.setEmotionTags(request.getEmotionTags());
    }
    if (request.getRiskScore() != null) {
      revised.setRiskScore(request.getRiskScore());
    }
    if (request.getTopic() != null) {
      revised.setTopic(OpinionText.trim(request.getTopic(), 256));
    }
    if (request.getStatus() != null) {
      revised.setStatus(request.getStatus());
    }
    revised.setVersion((original.getVersion() == null ? 1 : original.getVersion()) + 1);
    revised.setSource("manual");
    revised.setAuditedBy(OpinionCurrentUser.username());
    revised.setCreatedAt(null);
    revised.setUpdatedAt(null);
    analysisMapper.insert(revised);

    OpinionReview review = new OpinionReview();
    review.setTargetType("opinion_analysis");
    review.setTargetId(revised.getId());
    review.setField(request.getField());
    review.setOldValue(oldValue);
    review.setNewValue(snapshot(revised));
    review.setReason(OpinionText.trim(request.getReason(), 2000));
    review.setReviewedBy(OpinionCurrentUser.username());
    reviewMapper.insert(review);
    auditService.record(
        "ANALYSIS_REVIEW",
        "opinion_analysis",
        revised.getId(),
        Map.of("sourceAnalysisId", analysisId, "field", request.getField()),
        null);
    return revised;
  }

  public List<OpinionAnalysis> listByArticle(Long articleId) {
    OpinionArticle article = articleMapper.selectById(articleId);
    if (article == null) {
      throw new IllegalArgumentException("article not found");
    }
    if (article.getMonitorId() != null) {
      accessService.requireMonitor(article.getMonitorId());
    }
    return analysisMapper.selectList(
        Wrappers.<OpinionAnalysis>lambdaQuery()
            .eq(OpinionAnalysis::getArticleId, articleId)
            .orderByDesc(OpinionAnalysis::getVersion)
            .orderByDesc(OpinionAnalysis::getId));
  }

  private int nextAnalysisVersion(Long articleId, Long monitorId) {
    OpinionAnalysis latest =
        analysisMapper.selectOne(
            Wrappers.<OpinionAnalysis>lambdaQuery()
                .eq(OpinionAnalysis::getArticleId, articleId)
                .eq(OpinionAnalysis::getMonitorId, monitorId)
                .orderByDesc(OpinionAnalysis::getVersion)
                .last("LIMIT 1"));
    return latest == null || latest.getVersion() == null ? 1 : latest.getVersion() + 1;
  }

  private Map<String, Object> snapshot(OpinionAnalysis analysis) {
    Map<String, Object> snapshot = new LinkedHashMap<>();
    snapshot.put("sentiment", analysis.getSentiment());
    snapshot.put("confidence", analysis.getConfidence());
    snapshot.put("emotionTags", analysis.getEmotionTags());
    snapshot.put("riskScore", analysis.getRiskScore());
    snapshot.put("topic", analysis.getTopic());
    snapshot.put("status", analysis.getStatus());
    return snapshot;
  }

  private OpinionAnalysis copyOf(OpinionAnalysis source) {
    OpinionAnalysis copy = new OpinionAnalysis();
    copy.setArticleId(source.getArticleId());
    copy.setMonitorId(source.getMonitorId());
    copy.setSentiment(source.getSentiment());
    copy.setConfidence(source.getConfidence());
    copy.setEmotionTags(source.getEmotionTags());
    copy.setReason(source.getReason());
    copy.setEvidenceIds(source.getEvidenceIds());
    copy.setRiskFactors(source.getRiskFactors());
    copy.setRiskScore(source.getRiskScore());
    copy.setTopic(source.getTopic());
    copy.setKeywords(source.getKeywords());
    copy.setModel(source.getModel());
    copy.setPromptVersion(source.getPromptVersion());
    copy.setAiRunId(source.getAiRunId());
    copy.setStatus(source.getStatus());
    copy.setSource(source.getSource());
    copy.setAuditedBy(source.getAuditedBy());
    return copy;
  }
}
