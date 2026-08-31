package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.dto.OpinionPageQuery;
import com.eaos.admin.opinion.entity.OpinionArticle;
import com.eaos.admin.opinion.service.OpinionArticleService;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/opinion/articles")
@RequiredArgsConstructor
public class OpinionArticleController {

  private final OpinionArticleService service;

  @GetMapping
  public R<Map<String, Object>> page(
      @RequestParam(required = false) Long monitorId,
      @RequestParam(required = false) Long sourceId,
      @RequestParam(required = false) String keyword,
      @RequestParam(defaultValue = "1") Integer page,
      @RequestParam(defaultValue = "20") Integer pageSize) {
    OpinionPageQuery query = new OpinionPageQuery();
    query.setMonitorId(monitorId);
    query.setSourceId(sourceId);
    query.setKeyword(keyword);
    query.setPage(page);
    query.setPageSize(pageSize);
    return R.ok(service.queryPage(query));
  }

  @GetMapping("/{id}")
  public R<OpinionArticle> get(@PathVariable Long id) {
    return R.ok(service.get(id));
  }
}
