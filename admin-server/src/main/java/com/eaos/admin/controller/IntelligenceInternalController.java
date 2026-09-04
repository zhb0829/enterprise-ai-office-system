package com.eaos.admin.controller;

import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.service.IntelligenceAdminService;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Python Worker → Java 的情报权威数据回写/读取接口。
 *
 * <p>Java 是 source_config / collected_article / article_cluster / intelligence_report /
 * collection_task_log 的唯一 owner；Python 经本控制器落库，避免跨项目直接写表。 与其它 /internal/** 一致，令牌由调用方以
 * X-Internal-Token 携带（此处用 AI_INTERNAL_TOKEN）。
 */
@RestController
@RequestMapping("/internal/intelligence")
@RequiredArgsConstructor
public class IntelligenceInternalController {

  private final IntelligenceAdminService service;
  private final AiServiceProperties properties;

  @GetMapping("/ping")
  public Map<String, Object> ping(
      @RequestHeader(value = "X-Internal-Token", required = false) String token) {
    verify(token);
    return Map.of("ok", true, "service", "admin-server");
  }

  // ---------- 来源 ----------

  @GetMapping("/sources")
  public Map<String, Object> sources(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestParam(required = false) String status,
      @RequestParam(defaultValue = "500") int limit) {
    verify(token);
    return Map.of("items", service.listSourcesForWorker(status, limit));
  }

  @GetMapping("/sources/{id}")
  public Map<String, Object> source(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @PathVariable Long id) {
    verify(token);
    Map<String, Object> source = service.getSource(id);
    if (source == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "采集源不存在");
    return source;
  }

  @PostMapping("/sources/{id}/run-state")
  public Map<String, Object> runState(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @PathVariable Long id,
      @RequestBody Map<String, Object> state) {
    verify(token);
    return service.updateSourceRunState(id, state);
  }

  // ---------- 文章 ----------

  @PostMapping("/articles/batch")
  public Map<String, Object> ingest(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestBody Map<String, Object> body) {
    verify(token);
    Object sourceId = body.get("sourceId");
    if (!(sourceId instanceof Number)) {
      throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少 sourceId");
    }
    Object items = body.get("items");
    List<?> itemList = items instanceof List<?> list ? list : List.of();
    return service.ingestArticles(((Number) sourceId).longValue(), itemList);
  }

  @GetMapping("/articles")
  public Map<String, Object> articles(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestParam(required = false) Integer sinceDays,
      @RequestParam(required = false) String keyword,
      @RequestParam(required = false) Long sourceId,
      @RequestParam(required = false) Integer page,
      @RequestParam(required = false) Integer pageSize) {
    verify(token);
    return service.listArticles(sinceDays, keyword, sourceId, page, pageSize);
  }

  // ---------- 聚类 ----------

  @PostMapping("/clusters/replace")
  public Map<String, Object> replaceClusters(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestBody Map<String, Object> body) {
    verify(token);
    Object clusters = body.get("clusters");
    List<?> clusterList = clusters instanceof List<?> list ? list : List.of();
    return service.replaceClusters(clusterList);
  }

  @GetMapping("/clusters")
  public Map<String, Object> clusters(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestParam(required = false) Integer sinceDays,
      @RequestParam(required = false) String topic,
      @RequestParam(required = false) Integer limit) {
    verify(token);
    return Map.of("items", service.listClusters(sinceDays, topic, limit));
  }

  @GetMapping("/articles/by-ids")
  public Map<String, Object> articlesByIds(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestParam String ids) {
    verify(token);
    List<Long> parsed = new java.util.ArrayList<>();
    for (String part : ids.split(",")) {
      if (!part.isBlank()) {
        try {
          parsed.add(Long.valueOf(part.trim()));
        } catch (NumberFormatException ignored) {
          // 忽略非法 id
        }
      }
    }
    return service.listArticlesByIds(parsed);
  }

  @GetMapping("/clusters/{id}")
  public Map<String, Object> cluster(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @PathVariable Long id) {
    verify(token);
    Map<String, Object> cluster = service.getCluster(id);
    if (cluster == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "聚类不存在");
    return cluster;
  }

  // ---------- 采集任务 ----------

  @PostMapping("/tasks")
  public Map<String, Object> createTask(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestBody Map<String, Object> body) {
    verify(token);
    Object sourceId = body.get("sourceId");
    if (!(sourceId instanceof Number)) {
      throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少 sourceId");
    }
    Object retryCount = body.get("retryCount");
    int retries = retryCount instanceof Number number ? number.intValue() : 0;
    return service.createTaskInternal(((Number) sourceId).longValue(), retries);
  }

  @GetMapping("/tasks/{id}")
  public Map<String, Object> task(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @PathVariable Long id) {
    verify(token);
    Map<String, Object> task = service.getTask(id);
    if (task == null) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "采集任务不存在");
    return task;
  }

  @PostMapping("/tasks/{id}/start")
  public Map<String, Object> taskStart(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @PathVariable Long id) {
    verify(token);
    return service.markTaskStart(id);
  }

  @PostMapping("/tasks/{id}/result")
  public Map<String, Object> taskResult(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @PathVariable Long id,
      @RequestBody(required = false) Map<String, Object> body) {
    verify(token);
    Object itemsCount = body == null ? null : body.get("itemsCount");
    int items = itemsCount instanceof Number number ? number.intValue() : 0;
    return service.markTaskResult(id, items);
  }

  @PostMapping("/tasks/{id}/failure")
  public Map<String, Object> taskFailure(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @PathVariable Long id,
      @RequestBody Map<String, Object> body) {
    verify(token);
    Object error = body == null ? null : body.get("error");
    return service.markTaskFailure(id, error == null ? "" : String.valueOf(error));
  }

  // ---------- 简报 ----------

  @PostMapping("/reports")
  public Map<String, Object> saveReport(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestBody Map<String, Object> body) {
    verify(token);
    return service.saveReport(body);
  }

  @GetMapping("/reports")
  public Map<String, Object> reports(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestParam(required = false) String period,
      @RequestParam(required = false) Integer limit) {
    verify(token);
    return Map.of("items", service.listReportsInternal(period, limit));
  }

  private void verify(String token) {
    if (properties.getInternalToken() == null
        || properties.getInternalToken().isBlank()
        || !properties.getInternalToken().equals(token)) {
      throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "invalid internal token");
    }
  }
}
