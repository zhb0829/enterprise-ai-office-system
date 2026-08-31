package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.entity.OpinionSourceTask;
import com.eaos.admin.opinion.service.OpinionCollectService;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/opinion/collect")
@RequiredArgsConstructor
public class OpinionCollectController {

  private final OpinionCollectService service;

  @PostMapping("/source/{sourceId}")
  public R<OpinionSourceTask> triggerSource(
      @PathVariable Long sourceId, @RequestParam(required = false) Long monitorId) {
    return R.ok(service.triggerSource(sourceId, monitorId));
  }

  @PostMapping("/monitor/{monitorId}")
  public R<List<OpinionSourceTask>> triggerMonitor(@PathVariable Long monitorId) {
    return R.ok(service.triggerMonitor(monitorId));
  }

  @GetMapping("/tasks")
  public R<List<OpinionSourceTask>> tasks(
      @RequestParam(required = false) Long monitorId,
      @RequestParam(required = false) String status) {
    return R.ok(service.listTasks(monitorId, status));
  }
}
