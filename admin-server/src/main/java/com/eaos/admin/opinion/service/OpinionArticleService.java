package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.dto.IngestArticlesRequest;
import com.eaos.admin.opinion.dto.OpinionPageQuery;
import com.eaos.admin.opinion.entity.OpinionAnalysisTask;
import com.eaos.admin.opinion.entity.OpinionArticle;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import com.eaos.admin.opinion.entity.OpinionSource;
import com.eaos.admin.opinion.entity.OpinionSourceTask;
import com.eaos.admin.opinion.mapper.OpinionAnalysisTaskMapper;
import com.eaos.admin.opinion.mapper.OpinionArticleMapper;
import com.eaos.admin.opinion.mapper.OpinionMonitorMapper;
import com.eaos.admin.opinion.mapper.OpinionSourceMapper;
import com.eaos.admin.opinion.mapper.OpinionSourceTaskMapper;
import com.eaos.admin.opinion.support.OpinionAccessService;
import com.eaos.admin.opinion.support.OpinionText;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class OpinionArticleService {

  private final OpinionArticleMapper articleMapper;
  private final OpinionAnalysisTaskMapper taskMapper;
  private final OpinionMonitorMapper monitorMapper;
  private final OpinionSourceMapper sourceMapper;
  private final OpinionSourceTaskMapper sourceTaskMapper;
  private final OpinionAccessService accessService;

  /** 采集结果入库：去重 → 匹配监控词 → 生成待分析任务。幂等。 */
  @Transactional
  public Map<String, Object> ingest(IngestArticlesRequest request) {
    OpinionSource source = sourceMapper.selectById(request.getSourceId());
    if (source == null) {
      throw new IllegalArgumentException("采集源不存在");
    }
    OpinionMonitor monitor =
        request.getMonitorId() == null ? null : monitorMapper.selectById(request.getMonitorId());
    if (request.getMonitorId() != null && monitor == null) {
      throw new IllegalArgumentException("监控任务不存在");
    }

    Set<String> existing =
        new LinkedHashSet<>(
            articleMapper
                .selectList(Wrappers.<OpinionArticle>query().select("content_hash"))
                .stream()
                .map(OpinionArticle::getContentHash)
                .toList());

    long duplicates = 0;
    long created = 0;
    long tasks = 0;
    for (IngestArticlesRequest.IngestArticleItem item : request.getItems()) {
      String contentHash = item.getContentHash();
      if (contentHash == null || contentHash.isEmpty()) {
        contentHash = OpinionText.contentHash(item.getTitle(), item.getContent(), item.getUrl());
      }
      if (existing.contains(contentHash)) {
        duplicates++;
        continue;
      }
      List<String> matched =
          monitor == null
              ? List.of()
              : OpinionText.matchKeywords(monitor, item.getTitle(), item.getContent());
      boolean relevant = monitor == null || !matched.isEmpty();
      if (!relevant) {
        continue;
      }
      OpinionArticle article = new OpinionArticle();
      article.setSourceId(request.getSourceId());
      article.setMonitorId(request.getMonitorId());
      article.setTitle(OpinionText.trim(item.getTitle(), 512));
      article.setContent(OpinionText.trim(item.getContent(), 200000));
      article.setUrl(OpinionText.trim(item.getUrl(), 2048));
      article.setUrlHash(OpinionText.sha256(article.getUrl()));
      article.setContentHash(contentHash);
      article.setAuthor(OpinionText.trim(item.getAuthor(), 256));
      article.setPublishTime(parse(item.getPublishTime()));
      article.setMatchedKeywords(matched);
      article.setStatus("analysis_pending");
      articleMapper.insert(article);
      existing.add(contentHash);
      created++;

      if (request.getMonitorId() != null) {
        OpinionAnalysisTask task = new OpinionAnalysisTask();
        task.setArticleId(article.getId());
        task.setMonitorId(request.getMonitorId());
        task.setStatus("queued");
        long existed =
            taskMapper.selectCount(
                Wrappers.<OpinionAnalysisTask>lambdaQuery()
                    .eq(OpinionAnalysisTask::getArticleId, article.getId())
                    .eq(OpinionAnalysisTask::getMonitorId, request.getMonitorId()));
        if (existed == 0) {
          taskMapper.insert(task);
          tasks++;
        }
      }
    }
    finalizeSourceTask(request.getSourceTaskId(), source, request.getItems().size(), created);
    return Map.of(
        "received",
        (long) request.getItems().size(),
        "created",
        created,
        "duplicates",
        duplicates,
        "analysisTasks",
        tasks);
  }

  /** 采集任务收尾：标记成功 / 失败并记录收发数量。 */
  private void finalizeSourceTask(
      Long sourceTaskId, OpinionSource source, int received, long created) {
    if (sourceTaskId == null) {
      return;
    }
    OpinionSourceTask sourceTask = sourceTaskMapper.selectById(sourceTaskId);
    if (sourceTask == null) {
      return;
    }
    sourceTask.setStatus("success");
    sourceTask.setItemsSent(received);
    sourceTask.setItemsIngested((int) created);
    sourceTask.setFinishedAt(LocalDateTime.now());
    sourceTask.setUpdatedAt(LocalDateTime.now());
    sourceTaskMapper.updateById(sourceTask);
    source.setLastCollectAt(LocalDateTime.now());
    source.setLastSuccessAt(LocalDateTime.now());
    source.setHealthStatus("healthy");
    source.setFailureCount(0);
    source.setLastError("");
    source.setUpdatedAt(LocalDateTime.now());
    sourceMapper.updateById(source);
  }

  public Map<String, Object> queryPage(OpinionPageQuery query) {
    LambdaQueryWrapper<OpinionArticle> wrapper = Wrappers.lambdaQuery();
    if (query.getMonitorId() != null) {
      accessService.requireMonitor(query.getMonitorId());
      wrapper.eq(OpinionArticle::getMonitorId, query.getMonitorId());
    } else if (com.eaos.admin.opinion.support.OpinionCurrentUser.isAuthenticated()
        && !com.eaos.admin.opinion.support.OpinionCurrentUser.isAdmin()) {
      var ids = accessService.visibleMonitorIds();
      if (ids.isEmpty()) {
        return Map.of("items", List.of(), "total", 0, "page", 1, "pageSize", 1);
      }
      wrapper.in(OpinionArticle::getMonitorId, ids);
    }
    if (query.getSourceId() != null) {
      wrapper.eq(OpinionArticle::getSourceId, query.getSourceId());
    }
    if (query.getKeyword() != null && !query.getKeyword().isBlank()) {
      String like = "%" + query.getKeyword().trim() + "%";
      wrapper.and(
          w -> w.like(OpinionArticle::getTitle, like).or().like(OpinionArticle::getContent, like));
    }
    long total = articleMapper.selectCount(wrapper);
    int page = Math.max(1, query.getPage());
    int pageSize = Math.min(100, Math.max(1, query.getPageSize()));
    wrapper.orderByDesc(OpinionArticle::getCollectedAt);
    wrapper.last("LIMIT " + pageSize + " OFFSET " + ((page - 1) * pageSize));
    List<OpinionArticle> items = articleMapper.selectList(wrapper);
    return Map.of("items", items, "total", total, "page", page, "pageSize", pageSize);
  }

  @Transactional
  public void failSourceTask(Long sourceTaskId, String error) {
    OpinionSourceTask sourceTask = sourceTaskMapper.selectById(sourceTaskId);
    if (sourceTask == null || "success".equals(sourceTask.getStatus())) {
      return;
    }
    sourceTask.setStatus("failed");
    sourceTask.setError(OpinionText.trim(error, 4000));
    sourceTask.setFinishedAt(LocalDateTime.now());
    sourceTask.setUpdatedAt(LocalDateTime.now());
    sourceTask.setRetryCount(
        (sourceTask.getRetryCount() == null ? 0 : sourceTask.getRetryCount()) + 1);
    sourceTaskMapper.updateById(sourceTask);
    OpinionSource source = sourceMapper.selectById(sourceTask.getSourceId());
    if (source != null) {
      source.setFailureCount((source.getFailureCount() == null ? 0 : source.getFailureCount()) + 1);
      source.setHealthStatus("unhealthy");
      source.setLastError(OpinionText.trim(error, 4000));
      source.setUpdatedAt(LocalDateTime.now());
      sourceMapper.updateById(source);
    }
  }

  public OpinionArticle get(Long id) {
    OpinionArticle article = articleMapper.selectById(id);
    if (article == null) {
      throw new IllegalArgumentException("文章不存在");
    }
    if (article.getMonitorId() != null) {
      accessService.requireMonitor(article.getMonitorId());
    }
    return article;
  }

  private static LocalDateTime parse(String value) {
    if (value == null || value.isBlank()) {
      return null;
    }
    String v = value.trim();
    try {
      return LocalDateTime.parse(
          v.replace('T', ' '), DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
    } catch (Exception ignored) {
      // ignore
    }
    try {
      return LocalDateTime.parse(v, DateTimeFormatter.ofPattern("yyyy-MM-dd"));
    } catch (Exception ignored) {
      // ignore
    }
    return null;
  }
}
