package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.dto.AlertRuleRequest;
import com.eaos.admin.opinion.entity.OpinionAlertRule;
import com.eaos.admin.opinion.service.OpinionAlertRuleService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import jakarta.validation.Valid;
import java.util.List;
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
@RequestMapping("/api/opinion/alert-rules")
@RequiredArgsConstructor
public class OpinionAlertRuleController {

  private final OpinionAlertRuleService service;

  @GetMapping
  public R<List<OpinionAlertRule>> list(@RequestParam(required = false) Long monitorId) {
    requireAdmin();
    return R.ok(service.list(monitorId));
  }

  @PostMapping
  public R<OpinionAlertRule> create(@Valid @RequestBody AlertRuleRequest request) {
    requireAdmin();
    return R.ok(service.create(request));
  }

  @PutMapping("/{id}")
  public R<OpinionAlertRule> update(
      @PathVariable Long id, @Valid @RequestBody AlertRuleRequest request) {
    requireAdmin();
    return R.ok(service.update(id, request));
  }

  @DeleteMapping("/{id}")
  public R<Void> delete(@PathVariable Long id) {
    requireAdmin();
    service.delete(id);
    return R.ok();
  }

  @PostMapping("/{id}/toggle")
  public R<OpinionAlertRule> toggle(@PathVariable Long id) {
    requireAdmin();
    return R.ok(service.toggle(id));
  }

  private void requireAdmin() {
    if (!OpinionCurrentUser.isAdmin()) {
      throw new IllegalArgumentException("仅系统管理员可配置告警规则");
    }
  }
}
