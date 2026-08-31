package com.eaos.admin.opinion.controller;

import com.eaos.admin.opinion.dto.AnalysisFailureRequest;
import com.eaos.admin.opinion.dto.AnalysisResultRequest;
import com.eaos.admin.opinion.dto.IngestArticlesRequest;
import com.eaos.admin.opinion.dto.SourceTaskFailureRequest;
import com.eaos.admin.opinion.dto.SpreadIngestRequest;
import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionResponseCase;
import com.eaos.admin.opinion.service.OpinionAnalysisService;
import com.eaos.admin.opinion.service.OpinionArticleService;
import com.eaos.admin.opinion.service.OpinionResponseCaseService;
import com.eaos.admin.opinion.service.OpinionSpreadService;
import com.eaos.admin.opinion.support.InternalTokenVerifier;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/internal/opinion")
@RequiredArgsConstructor
public class OpinionInternalController {

  private final OpinionArticleService articleService;
  private final OpinionAnalysisService analysisService;
  private final OpinionSpreadService spreadService;
  private final OpinionResponseCaseService responseCaseService;
  private final InternalTokenVerifier tokenVerifier;

  @GetMapping("/ping")
  public Map<String, Object> ping(HttpServletRequest http) {
    requireToken(http);
    return Map.of("ok", true, "service", "admin-server");
  }

  /** Python Worker 回传采集结果：入库 + 去重 + 匹配 + 生成分析任务。 */
  @PostMapping("/articles/ingest")
  public Map<String, Object> ingest(
      @Valid @RequestBody IngestArticlesRequest request, HttpServletRequest http) {
    requireToken(http);
    return articleService.ingest(request);
  }

  @PostMapping("/source-tasks/{taskId}/failure")
  public Map<String, Object> sourceTaskFailure(
      @PathVariable Long taskId,
      @Valid @RequestBody SourceTaskFailureRequest request,
      HttpServletRequest http) {
    requireToken(http);
    articleService.failSourceTask(taskId, request.getError());
    return Map.of("ok", true, "taskId", taskId, "status", "failed");
  }

  /** Python Worker 领取下一条待分析任务；无任务返回 204 风格空体。 */
  @GetMapping("/analysis/next")
  public Map<String, Object> next(
      @RequestParam(defaultValue = "python-worker") String worker, HttpServletRequest http) {
    requireToken(http);
    Map<String, Object> task = analysisService.claimNext(worker);
    if (task == null) {
      throw new ResponseStatusException(HttpStatus.NO_CONTENT, "暂无待分析任务");
    }
    return Map.of("ok", true, "task", task);
  }

  /** Python Worker 提交分析结果。 */
  @PostMapping("/analysis/{taskId}/result")
  public Map<String, Object> result(
      @PathVariable Long taskId,
      @Valid @RequestBody AnalysisResultRequest request,
      HttpServletRequest http) {
    requireToken(http);
    request.setTaskId(taskId);
    OpinionAnalysis analysis = analysisService.submitResult(request);
    return Map.of("ok", true, "analysisId", analysis.getId(), "status", analysis.getStatus());
  }

  @PostMapping("/analysis/{taskId}/failure")
  public Map<String, Object> failure(
      @PathVariable Long taskId,
      @Valid @RequestBody AnalysisFailureRequest request,
      HttpServletRequest http) {
    requireToken(http);
    analysisService.failTask(taskId, request.getError());
    return Map.of("ok", true, "taskId", taskId, "status", "failed");
  }

  /** Python 传播分析结果回传（已验证/推测分字段保存）。 */
  @PostMapping("/spread/ingest")
  public Map<String, Object> spreadIngest(
      @Valid @RequestBody SpreadIngestRequest request, HttpServletRequest http) {
    requireToken(http);
    return spreadService.ingest(request);
  }

  /** Python RAG 建索引用：读取全部历史案例。 */
  @GetMapping("/cases/all")
  public Map<String, Object> casesAll(HttpServletRequest http) {
    requireToken(http);
    java.util.List<OpinionResponseCase> cases = responseCaseService.listAll();
    java.util.List<Map<String, Object>> items = new java.util.ArrayList<>();
    for (OpinionResponseCase c : cases) {
      items.add(
          Map.of(
              "id", c.getId(),
              "title", c.getTitle(),
              "eventType", c.getEventType(),
              "riskLevel", c.getRiskLevel(),
              "strategy", c.getStrategy(),
              "content", c.getContent(),
              "effect", c.getEffect(),
              "tags", c.getTags() == null ? java.util.List.of() : c.getTags(),
              "source", c.getSource()));
    }
    return Map.of("ok", true, "cases", items);
  }

  private void requireToken(HttpServletRequest request) {
    if (!tokenVerifier.verify(request)) {
      throw new ResponseStatusException(HttpStatus.FORBIDDEN, "invalid internal token");
    }
  }
}
