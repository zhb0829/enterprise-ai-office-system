package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.dto.ResponseCaseRequest;
import com.eaos.admin.opinion.entity.OpinionResponseCase;
import com.eaos.admin.opinion.service.OpinionResponseCaseService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import jakarta.validation.Valid;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/opinion/cases")
@RequiredArgsConstructor
public class OpinionResponseCaseController {

  private final OpinionResponseCaseService service;

  @GetMapping
  public R<List<OpinionResponseCase>> list(
      @RequestParam(required = false) String eventType,
      @RequestParam(required = false) String riskLevel,
      @RequestParam(required = false) String keyword) {
    return R.ok(service.list(eventType, riskLevel, keyword));
  }

  @PostMapping
  public R<OpinionResponseCase> create(@Valid @RequestBody ResponseCaseRequest request) {
    requireAdmin();
    return R.ok(service.create(request));
  }

  @PutMapping("/{id}")
  public R<OpinionResponseCase> update(
      @PathVariable Long id, @Valid @RequestBody ResponseCaseRequest request) {
    requireAdmin();
    return R.ok(service.update(id, request));
  }

  @DeleteMapping("/{id}")
  public R<Void> delete(@PathVariable Long id) {
    requireAdmin();
    service.delete(id);
    return R.ok();
  }

  @PostMapping("/reindex")
  public R<Map<String, Object>> reindex() {
    requireAdmin();
    return R.ok(service.reindex());
  }

  private void requireAdmin() {
    if (!OpinionCurrentUser.isAdmin()) {
      throw new IllegalArgumentException("仅系统管理员可维护历史案例");
    }
  }
}
