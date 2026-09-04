package com.eaos.admin.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.dto.SourceConfigRequest;
import com.eaos.admin.entity.ArticleCluster;
import com.eaos.admin.entity.CollectedArticle;
import com.eaos.admin.entity.CollectionTaskLog;
import com.eaos.admin.entity.IntelligenceReport;
import com.eaos.admin.entity.SourceConfig;
import com.eaos.admin.mapper.ArticleClusterMapper;
import com.eaos.admin.mapper.CollectedArticleMapper;
import com.eaos.admin.mapper.CollectionTaskLogMapper;
import com.eaos.admin.mapper.IntelligenceReportMapper;
import com.eaos.admin.mapper.SourceConfigMapper;
import java.time.LocalDateTime;
import java.time.format.DateTimeParseException;
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

/**
 * 行业情报采集与管理（owner：Java）。
 *
 * <p>Java 负责权威表（source_config / collected_article / article_cluster / intelligence_report /
 * collection_task_log）与任务生命周期；Python Worker 仅提供采集与 AI 能力， 通过 /internal/intelligence/** 回写与读取（见
 * IntelligenceInternalController）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class IntelligenceAdminService {
  private final SourceConfigMapper sourceConfigMapper;
  private final CollectionTaskLogMapper taskLogMapper;
  private final CollectedArticleMapper articleMapper;
  private final ArticleClusterMapper clusterMapper;
  private final IntelligenceReportMapper reportMapper;
  private final RestTemplate restTemplate;
  private final AiServiceProperties aiProperties;

  // ---------- 管理端：采集源 CRUD ----------

  public List<SourceConfig> listSources() {
    return sourceConfigMapper.selectList(Wrappers.<SourceConfig>query().orderByDesc("id"));
  }

  public SourceConfig saveSource(Long id, SourceConfigRequest request) {
    SourceConfig source = id == null ? new SourceConfig() : sourceConfigMapper.selectById(id);
    if (source == null) throw new IllegalArgumentException("采集源不存在");
    String url = request.getUrl().trim();
    var duplicateUrlQuery = Wrappers.<SourceConfig>query().eq("url", url);
    if (id != null) duplicateUrlQuery.ne("id", id);
    if (sourceConfigMapper.selectCount(duplicateUrlQuery) > 0) {
      throw new IllegalArgumentException("该采集来源 URL 已存在，请直接使用或修改现有来源");
    }

    source.setName(request.getName().trim());
    source.setType(request.getType());
    source.setUrl(url);
    source.setKeywords(request.getKeywords());
    source.setCompetitors(request.getCompetitors());
    source.setFrequency(request.getFrequency());
    source.setStatus(request.getStatus());
    if (source.getHealthStatus() == null) source.setHealthStatus("unknown");
    if (id == null) sourceConfigMapper.insert(source);
    else sourceConfigMapper.updateById(source);
    return sourceConfigMapper.selectById(source.getId());
  }

  public void deleteSource(Long id) {
    if (sourceConfigMapper.deleteById(id) == 0) throw new IllegalArgumentException("采集源不存在");
  }

  public SourceConfig toggle(Long id) {
    SourceConfig source = sourceConfigMapper.selectById(id);
    if (source == null) throw new IllegalArgumentException("采集源不存在");
    source.setStatus("enabled".equalsIgnoreCase(source.getStatus()) ? "paused" : "enabled");
    sourceConfigMapper.updateById(source);
    return sourceConfigMapper.selectById(id);
  }

  // ---------- 管理端：手动运行 / 重试 / 生成报告（Java 建任务，Python 执行） ----------

  public Map<String, Object> trigger(Long sourceId) {
    SourceConfig source = sourceConfigMapper.selectById(sourceId);
    if (source == null) throw new IllegalArgumentException("采集源不存在");
    CollectionTaskLog task = createTask(sourceId, 0);
    dispatchToPython("/internal/intelligence/tasks/" + task.getId() + "/dispatch");
    return taskView(task);
  }

  public Map<String, Object> retry(Long taskId) {
    CollectionTaskLog old = taskLogMapper.selectById(taskId);
    if (old == null) throw new IllegalArgumentException("采集任务不存在");
    SourceConfig source = sourceConfigMapper.selectById(old.getSourceId());
    if (source == null) throw new IllegalArgumentException("采集源不存在");
    int retryCount = (old.getRetryCount() == null ? 0 : old.getRetryCount()) + 1;
    CollectionTaskLog task = createTask(old.getSourceId(), retryCount);
    dispatchToPython("/internal/intelligence/tasks/" + task.getId() + "/dispatch");
    return taskView(task);
  }

  public Map<String, Object> generateReport(String period) {
    return postToPython("/internal/intelligence/reports/generate?period=" + period, Map.of());
  }

  public List<CollectionTaskLog> listTasks(String status, Long sourceId) {
    var wrapper = Wrappers.<CollectionTaskLog>query().orderByDesc("created_at");
    if (status != null && !status.isBlank()) wrapper.eq("status", status);
    if (sourceId != null) wrapper.eq("source_id", sourceId);
    return taskLogMapper.selectList(wrapper);
  }

  private CollectionTaskLog createTask(Long sourceId, int retryCount) {
    CollectionTaskLog task = new CollectionTaskLog();
    task.setSourceId(sourceId);
    task.setStatus("queued");
    task.setRetryCount(retryCount);
    taskLogMapper.insert(task);
    return taskLogMapper.selectById(task.getId());
  }

  private void dispatchToPython(String path) {
    try {
      postToPython(path, Map.of());
    } catch (Exception exc) {
      log.error("情报任务派发 Python 失败 {}: {}", path, exc.getMessage());
    }
  }

  private Map<String, Object> postToPython(String path, Object body) {
    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    headers.set("X-Internal-Token", aiProperties.getInternalToken());
    Map<String, Object> payload =
        restTemplate.postForObject(
            aiProperties.getBaseUrl() + path, new HttpEntity<>(body, headers), Map.class);
    return payload == null ? Map.of() : payload;
  }

  private Map<String, Object> taskView(CollectionTaskLog task) {
    Map<String, Object> view = new LinkedHashMap<>();
    view.put("id", task.getId());
    view.put("sourceId", task.getSourceId());
    view.put("status", task.getStatus());
    view.put("retryCount", task.getRetryCount());
    view.put("createdAt", task.getCreatedAt());
    view.put("startedAt", task.getStartedAt());
    view.put("finishedAt", task.getFinishedAt());
    view.put("itemsCount", task.getItemsCount());
    view.put("error", task.getError());
    return view;
  }

  // ---------- Python Worker 内部接口的数据操作（/internal/intelligence/**） ----------

  public Map<String, Object> getSource(Long id) {
    SourceConfig source = sourceConfigMapper.selectById(id);
    if (source == null) return null;
    return sourceView(source);
  }

  public List<Map<String, Object>> listSourcesForWorker(String status, int limit) {
    var wrapper = Wrappers.<SourceConfig>query().orderByAsc("id");
    if (status != null && !status.isBlank()) wrapper.eq("status", status);
    wrapper.last("LIMIT " + Math.max(1, Math.min(limit, 500)));
    List<Map<String, Object>> rows = new ArrayList<>();
    for (SourceConfig source : sourceConfigMapper.selectList(wrapper)) {
      rows.add(sourceView(source));
    }
    return rows;
  }

  private Map<String, Object> sourceView(SourceConfig source) {
    Map<String, Object> view = new LinkedHashMap<>();
    view.put("id", source.getId());
    view.put("name", source.getName());
    view.put("type", source.getType());
    view.put("url", source.getUrl());
    view.put("keywords", source.getKeywords() == null ? List.of() : source.getKeywords());
    view.put("competitors", source.getCompetitors() == null ? List.of() : source.getCompetitors());
    view.put("frequency", source.getFrequency());
    view.put("status", source.getStatus());
    view.put("healthStatus", source.getHealthStatus());
    view.put("consecutiveFailures", source.getConsecutiveFailures());
    view.put("lastRunAt", source.getLastRunAt());
    view.put("lastSuccessAt", source.getLastSuccessAt());
    view.put("lastError", source.getLastError());
    return view;
  }

  /** Python Worker 在采集前后回写来源运行状态。 */
  @Transactional
  public Map<String, Object> updateSourceRunState(Long id, Map<String, Object> state) {
    SourceConfig source = sourceConfigMapper.selectById(id);
    if (source == null) throw new IllegalArgumentException("采集源不存在");
    if (state.containsKey("healthStatus")) source.setHealthStatus(str(state.get("healthStatus")));
    if (state.containsKey("consecutiveFailures")) {
      Object value = state.get("consecutiveFailures");
      source.setConsecutiveFailures(value == null ? 0 : ((Number) value).intValue());
    }
    if (state.containsKey("status") && state.get("status") != null) {
      source.setStatus(str(state.get("status")));
    }
    if (state.get("lastRunAt") != null) source.setLastRunAt(parseTime(state.get("lastRunAt")));
    if (state.get("lastSuccessAt") != null) {
      source.setLastSuccessAt(parseTime(state.get("lastSuccessAt")));
    }
    if (state.containsKey("lastError")) {
      source.setLastError(str(state.get("lastError")) == null ? "" : str(state.get("lastError")));
    }
    sourceConfigMapper.updateById(source);
    return sourceView(source);
  }

  /** Python Worker 回传采集文章：按 content_hash 去重后入库。 */
  @Transactional
  public Map<String, Object> ingestArticles(Long sourceId, List<?> items) {
    SourceConfig source = sourceConfigMapper.selectById(sourceId);
    if (source == null) throw new IllegalArgumentException("采集源不存在");
    if (items == null || items.isEmpty()) return Map.of("inserted", 0, "skipped", 0);

    var existing =
        articleMapper.selectList(
            Wrappers.<CollectedArticle>query().select("content_hash").last("LIMIT 200000"));
    java.util.Set<String> hashes = new java.util.HashSet<>();
    for (CollectedArticle article : existing) {
      if (article.getContentHash() != null) hashes.add(article.getContentHash());
    }

    int inserted = 0;
    for (Object raw : items) {
      if (!(raw instanceof Map<?, ?>)) continue;
      Map<?, ?> item = (Map<?, ?>) raw;
      String contentHash = str(item.get("contentHash"));
      if (contentHash == null || contentHash.isBlank()) {
        String url = str(item.get("url"));
        contentHash =
            digestHash(str(item.get("title")), str(item.get("content")), url == null ? "" : url);
      }
      if (hashes.contains(contentHash)) continue;
      CollectedArticle article = new CollectedArticle();
      article.setSourceId(sourceId);
      article.setTitle(str(item.get("title")) == null ? "" : str(item.get("title")));
      article.setContent(str(item.get("content")) == null ? "" : str(item.get("content")));
      article.setUrl(str(item.get("url")) == null ? "" : str(item.get("url")));
      article.setAuthor(str(item.get("author")) == null ? "" : str(item.get("author")));
      if (item.get("publishTime") != null)
        article.setPublishTime(parseTime(item.get("publishTime")));
      article.setContentHash(contentHash);
      article.setTitleHash(str(item.get("titleHash")) == null ? "" : str(item.get("titleHash")));
      if (item.get("status") != null) article.setStatus(str(item.get("status")));
      if (item.get("embedding") instanceof List<?> embedding) {
        article.setEmbedding(new ArrayList<>(embedding));
      } else {
        article.setEmbedding(List.of());
      }
      if (item.get("meta") instanceof Map<?, ?> meta) {
        Map<String, Object> metaMap = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : meta.entrySet()) {
          if (entry.getKey() != null) metaMap.put(String.valueOf(entry.getKey()), entry.getValue());
        }
        article.setMeta(metaMap);
      } else {
        article.setMeta(Map.of());
      }
      try {
        articleMapper.insert(article);
        hashes.add(contentHash);
        inserted++;
      } catch (Exception exc) {
        log.warn("情报文章入库冲突（content_hash 唯一约束）: {}", exc.getMessage());
      }
    }
    return Map.of("inserted", inserted, "skipped", items.size() - inserted);
  }

  /** 供 Python 聚类与用户端浏览：带来源名与分页的列表。 */
  public Map<String, Object> listArticles(
      Integer sinceDays, String keyword, Long sourceId, Integer page, Integer pageSize) {
    int pageNo = page == null ? 1 : Math.max(1, page);
    int size = pageSize == null ? 20 : Math.min(Math.max(1, pageSize), 100);
    var wrapper = Wrappers.<CollectedArticle>query().orderByDesc("collected_at");
    if (sinceDays != null && sinceDays > 0) {
      wrapper.ge("collected_at", LocalDateTime.now().minusDays(sinceDays));
    }
    if (sourceId != null) wrapper.eq("source_id", sourceId);
    if (keyword != null && !keyword.isBlank()) {
      wrapper.and(w -> w.like("title", keyword.trim()).or().like("content", keyword.trim()));
    }
    Long total = articleMapper.selectCount(wrapper);
    wrapper.last("LIMIT " + size + " OFFSET " + ((pageNo - 1) * size));
    return Map.of(
        "items",
        articleViews(articleMapper.selectList(wrapper)),
        "total",
        total == null ? 0 : total);
  }

  private List<Map<String, Object>> articleViews(List<CollectedArticle> articles) {
    Map<Long, String> sourceNames = new LinkedHashMap<>();
    for (CollectedArticle article : articles) {
      if (article.getSourceId() != null && !sourceNames.containsKey(article.getSourceId())) {
        SourceConfig source = sourceConfigMapper.selectById(article.getSourceId());
        sourceNames.put(article.getSourceId(), source == null ? "" : source.getName());
      }
    }
    List<Map<String, Object>> rows = new ArrayList<>();
    for (CollectedArticle article : articles) {
      Map<String, Object> view = new LinkedHashMap<>();
      view.put("id", article.getId());
      view.put("sourceId", article.getSourceId());
      view.put("sourceName", sourceNames.getOrDefault(article.getSourceId(), ""));
      view.put("title", article.getTitle());
      view.put("content", article.getContent());
      view.put("url", article.getUrl());
      view.put("author", article.getAuthor());
      view.put("publishTime", article.getPublishTime());
      view.put("collectedAt", article.getCollectedAt());
      view.put("contentHash", article.getContentHash());
      view.put("titleHash", article.getTitleHash());
      view.put("status", article.getStatus());
      view.put("embedding", article.getEmbedding() == null ? List.of() : article.getEmbedding());
      view.put("meta", article.getMeta() == null ? Map.of() : article.getMeta());
      rows.add(view);
    }
    return rows;
  }

  /** Python Worker 完成聚类后全量重建 article_cluster。 */
  @Transactional
  public Map<String, Object> replaceClusters(List<?> clusters) {
    clusterMapper.delete(Wrappers.<ArticleCluster>query().gt("id", 0));
    if (clusters == null || clusters.isEmpty()) return Map.of("created", 0);
    int created = 0;
    for (Object raw : clusters) {
      if (!(raw instanceof Map<?, ?> item)) continue;
      ArticleCluster cluster = new ArticleCluster();
      cluster.setTopic(str(item.get("topic")));
      cluster.setSummary(str(item.get("summary")) == null ? "" : str(item.get("summary")));
      if (item.get("articleIds") instanceof List<?> ids)
        cluster.setArticleIds(new ArrayList<>(ids));
      else cluster.setArticleIds(List.of());
      Object count = item.get("reportCount");
      cluster.setReportCount(count == null ? 0 : ((Number) count).intValue());
      if (item.get("timeStart") != null) cluster.setTimeStart(parseTime(item.get("timeStart")));
      if (item.get("timeEnd") != null) cluster.setTimeEnd(parseTime(item.get("timeEnd")));
      if (item.get("sources") instanceof List<?> sources)
        cluster.setSources(new ArrayList<>(sources));
      else cluster.setSources(List.of());
      if (item.get("meta") instanceof Map<?, ?> meta) {
        Map<String, Object> metaMap = new LinkedHashMap<>();
        for (Map.Entry<?, ?> entry : meta.entrySet()) {
          if (entry.getKey() != null) metaMap.put(String.valueOf(entry.getKey()), entry.getValue());
        }
        cluster.setMeta(metaMap);
      } else {
        cluster.setMeta(Map.of());
      }
      clusterMapper.insert(cluster);
      created++;
    }
    return Map.of("created", created);
  }

  /** 供 Python 报告生成读取聚类。 */
  public List<Map<String, Object>> listClusters(Integer sinceDays, String topic, Integer limit) {
    var wrapper =
        Wrappers.<ArticleCluster>query().orderByDesc("report_count").orderByDesc("updated_at");
    if (sinceDays != null && sinceDays > 0) {
      wrapper.ge("time_end", LocalDateTime.now().minusDays(sinceDays));
    }
    if (topic != null && !topic.isBlank()) wrapper.like("topic", topic.trim());
    int max = limit == null ? 50 : Math.min(Math.max(1, limit), 200);
    wrapper.last("LIMIT " + max);
    List<Map<String, Object>> rows = new ArrayList<>();
    for (ArticleCluster cluster : clusterMapper.selectList(wrapper)) {
      rows.add(clusterView(cluster));
    }
    return rows;
  }

  /** 供 Python 摘要/报告按 id 读取单个聚类。 */
  public Map<String, Object> getCluster(Long id) {
    ArticleCluster cluster = clusterMapper.selectById(id);
    return cluster == null ? null : clusterView(cluster);
  }

  private Map<String, Object> clusterView(ArticleCluster cluster) {
    Map<String, Object> view = new LinkedHashMap<>();
    view.put("id", cluster.getId());
    view.put("topic", cluster.getTopic());
    view.put("summary", cluster.getSummary());
    view.put("articleIds", cluster.getArticleIds() == null ? List.of() : cluster.getArticleIds());
    view.put("reportCount", cluster.getReportCount());
    view.put("timeStart", cluster.getTimeStart());
    view.put("timeEnd", cluster.getTimeEnd());
    view.put("sources", cluster.getSources() == null ? List.of() : cluster.getSources());
    view.put("meta", cluster.getMeta() == null ? Map.of() : cluster.getMeta());
    return view;
  }

  /** 供 Python 按文章 id 批量读取（摘要/报告上下文），单次最多 200 条。 */
  public Map<String, Object> listArticlesByIds(List<Long> ids) {
    if (ids == null || ids.isEmpty()) return Map.of("items", List.of());
    List<Long> limited = ids.size() > 200 ? ids.subList(0, 200) : ids;
    var wrapper = Wrappers.<CollectedArticle>query().in("id", limited);
    return Map.of("items", articleViews(articleMapper.selectList(wrapper)));
  }

  /** Python Worker 创建任务（Beat 定时触发时使用）。 */
  public Map<String, Object> createTaskInternal(Long sourceId, Integer retryCount) {
    SourceConfig source = sourceConfigMapper.selectById(sourceId);
    if (source == null) throw new IllegalArgumentException("采集源不存在");
    CollectionTaskLog task = createTask(sourceId, retryCount == null ? 0 : retryCount);
    return taskView(task);
  }

  public Map<String, Object> getTask(Long id) {
    CollectionTaskLog task = taskLogMapper.selectById(id);
    return task == null ? null : taskView(task);
  }

  @Transactional
  public Map<String, Object> markTaskStart(Long id) {
    CollectionTaskLog task = taskLogMapper.selectById(id);
    if (task == null) throw new IllegalArgumentException("采集任务不存在");
    task.setStatus("running");
    task.setStartedAt(LocalDateTime.now());
    taskLogMapper.updateById(task);
    return taskView(task);
  }

  @Transactional
  public Map<String, Object> markTaskResult(Long id, Integer itemsCount) {
    CollectionTaskLog task = taskLogMapper.selectById(id);
    if (task == null) throw new IllegalArgumentException("采集任务不存在");
    task.setStatus("success");
    task.setItemsCount(itemsCount == null ? 0 : itemsCount);
    task.setFinishedAt(LocalDateTime.now());
    taskLogMapper.updateById(task);
    return taskView(task);
  }

  @Transactional
  public Map<String, Object> markTaskFailure(Long id, String error) {
    CollectionTaskLog task = taskLogMapper.selectById(id);
    if (task == null) throw new IllegalArgumentException("采集任务不存在");
    task.setStatus("failed");
    task.setError(error == null ? "" : error.substring(0, Math.min(error.length(), 4000)));
    task.setFinishedAt(LocalDateTime.now());
    taskLogMapper.updateById(task);
    return taskView(task);
  }

  /** Python Worker 保存生成的简报，返回带 id 的行。 */
  @Transactional
  public Map<String, Object> saveReport(Map<String, Object> payload) {
    IntelligenceReport report = new IntelligenceReport();
    report.setTitle(str(payload.get("title")));
    report.setPeriod(str(payload.get("period")));
    if (payload.get("topicTags") instanceof List<?> tags) {
      List<String> topicTags = new ArrayList<>();
      for (Object tag : tags) topicTags.add(String.valueOf(tag));
      report.setTopicTags(topicTags);
    } else {
      report.setTopicTags(List.of());
    }
    if (payload.get("items") instanceof List<?> items) {
      List<Map<String, Object>> mapItems = new ArrayList<>();
      for (Object item : items) {
        if (item instanceof Map<?, ?> entry) {
          Map<String, Object> map = new LinkedHashMap<>();
          for (Map.Entry<?, ?> e : entry.entrySet()) {
            if (e.getKey() != null) map.put(String.valueOf(e.getKey()), e.getValue());
          }
          mapItems.add(map);
        }
      }
      report.setItems(mapItems);
    } else {
      report.setItems(List.of());
    }
    if (payload.get("trend") instanceof Map<?, ?> trend) {
      Map<String, Object> trendMap = new LinkedHashMap<>();
      for (Map.Entry<?, ?> entry : trend.entrySet()) {
        if (entry.getKey() != null) trendMap.put(String.valueOf(entry.getKey()), entry.getValue());
      }
      report.setTrend(trendMap);
    } else {
      report.setTrend(Map.of());
    }
    if (payload.get("sources") instanceof List<?> sources) {
      List<Map<String, Object>> mapSources = new ArrayList<>();
      for (Object item : sources) {
        if (item instanceof Map<?, ?> entry) {
          Map<String, Object> map = new LinkedHashMap<>();
          for (Map.Entry<?, ?> e : entry.entrySet()) {
            if (e.getKey() != null) map.put(String.valueOf(e.getKey()), e.getValue());
          }
          mapSources.add(map);
        }
      }
      report.setSources(mapSources);
    } else {
      report.setSources(List.of());
    }
    report.setModel(str(payload.get("model")) == null ? "" : str(payload.get("model")));
    if (payload.get("riskFlags") instanceof List<?> flags) {
      List<String> riskFlags = new ArrayList<>();
      for (Object flag : flags) riskFlags.add(String.valueOf(flag));
      report.setRiskFlags(riskFlags);
    } else {
      report.setRiskFlags(List.of());
    }
    report.setGeneratedAt(LocalDateTime.now());
    reportMapper.insert(report);
    return reportView(reportMapper.selectById(report.getId()));
  }

  public List<Map<String, Object>> listReportsInternal(String period, Integer limit) {
    var wrapper = Wrappers.<IntelligenceReport>query().orderByDesc("generated_at");
    if (period != null && !period.isBlank()) wrapper.eq("period", period);
    int max = limit == null ? 50 : Math.min(Math.max(1, limit), 200);
    wrapper.last("LIMIT " + max);
    List<Map<String, Object>> rows = new ArrayList<>();
    for (IntelligenceReport report : reportMapper.selectList(wrapper)) {
      rows.add(reportView(report));
    }
    return rows;
  }

  private Map<String, Object> reportView(IntelligenceReport report) {
    Map<String, Object> view = new LinkedHashMap<>();
    view.put("id", report.getId());
    view.put("title", report.getTitle());
    view.put("period", report.getPeriod());
    view.put("topicTags", report.getTopicTags() == null ? List.of() : report.getTopicTags());
    view.put("items", report.getItems() == null ? List.of() : report.getItems());
    view.put("trend", report.getTrend() == null ? Map.of() : report.getTrend());
    view.put("sources", report.getSources() == null ? List.of() : report.getSources());
    view.put("generatedAt", report.getGeneratedAt());
    view.put("model", report.getModel());
    view.put("riskFlags", report.getRiskFlags() == null ? List.of() : report.getRiskFlags());
    return view;
  }

  // ---------- 工具 ----------

  private String digestHash(String title, String content, String url) {
    String normalized = String.valueOf(title == null ? "" : title).toLowerCase().trim();
    return java.util.HexFormat.of()
        .formatHex(
            sha256Bytes(
                normalized
                    + "\n"
                    + String.valueOf(content == null ? "" : content).toLowerCase().trim()
                    + "\n"
                    + url));
  }

  private byte[] sha256Bytes(String value) {
    try {
      var digest = java.security.MessageDigest.getInstance("SHA-256");
      return digest.digest(value.getBytes(java.nio.charset.StandardCharsets.UTF_8));
    } catch (Exception exc) {
      throw new IllegalStateException(exc);
    }
  }

  private LocalDateTime parseTime(Object value) {
    if (value instanceof LocalDateTime dt) return dt;
    if (value == null) return null;
    try {
      return LocalDateTime.parse(String.valueOf(value));
    } catch (DateTimeParseException exc) {
      try {
        return java.time.OffsetDateTime.parse(String.valueOf(value)).toLocalDateTime();
      } catch (DateTimeParseException ignored) {
        return null;
      }
    }
  }

  private String str(Object value) {
    return value == null ? null : String.valueOf(value);
  }
}
