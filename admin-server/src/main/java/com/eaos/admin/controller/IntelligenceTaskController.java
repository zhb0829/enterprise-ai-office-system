package com.eaos.admin.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.entity.CollectionTaskLog;
import com.eaos.admin.service.IntelligenceAdminService;
import java.util.List;
import java.util.Map;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/intelligence/tasks")
@RequiredArgsConstructor
public class IntelligenceTaskController {
  private final IntelligenceAdminService service;

  @GetMapping
  public R<List<CollectionTaskLog>> list(
      @RequestParam(required = false) String status,
      @RequestParam(required = false) Long sourceId) {
    return R.ok(service.listTasks(status, sourceId));
  }

  @PostMapping("/{id}/retry")
  public R<Map<String, Object>> retry(@PathVariable Long id) {
    return R.ok(service.retry(id));
  }
}
