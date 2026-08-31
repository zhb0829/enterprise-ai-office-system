package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.dto.ReviewRequest;
import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.service.OpinionAnalysisService;
import jakarta.validation.Valid;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/opinion/analysis")
@RequiredArgsConstructor
public class OpinionAnalysisController {

  private final OpinionAnalysisService service;

  @GetMapping("/article/{articleId}")
  public R<List<OpinionAnalysis>> listByArticle(@PathVariable Long articleId) {
    return R.ok(service.listByArticle(articleId));
  }

  /** 人工复核/修正（形成新版本并记录审计）。 */
  @PostMapping("/{analysisId}/review")
  public R<OpinionAnalysis> review(
      @PathVariable Long analysisId, @Valid @RequestBody ReviewRequest request) {
    return R.ok(service.review(analysisId, request));
  }
}
