package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.dto.OpinionSourceRequest;
import com.eaos.admin.opinion.dto.SourceAuditRequest;
import com.eaos.admin.opinion.entity.OpinionSource;
import com.eaos.admin.opinion.service.OpinionSourceService;
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
@RequestMapping("/api/opinion/sources")
@RequiredArgsConstructor
public class OpinionSourceController {

  private final OpinionSourceService service;

  @GetMapping
  public R<List<OpinionSource>> list(
      @RequestParam(required = false) String auditStatus,
      @RequestParam(required = false) String status) {
    return R.ok(service.list(auditStatus, status));
  }

  @GetMapping("/{id}")
  public R<OpinionSource> get(@PathVariable Long id) {
    return R.ok(service.get(id));
  }

  @PostMapping
  public R<OpinionSource> create(@Valid @RequestBody OpinionSourceRequest request) {
    return R.ok(service.create(request, OpinionCurrentUser.isAdmin()));
  }

  @PutMapping("/{id}")
  public R<OpinionSource> update(
      @PathVariable Long id, @Valid @RequestBody OpinionSourceRequest request) {
    return R.ok(service.update(id, request, OpinionCurrentUser.isAdmin()));
  }

  @DeleteMapping("/{id}")
  public R<Void> delete(@PathVariable Long id) {
    service.delete(id, OpinionCurrentUser.isAdmin());
    return R.ok();
  }

  @PostMapping("/{id}/toggle")
  public R<OpinionSource> toggle(@PathVariable Long id) {
    return R.ok(service.toggle(id, OpinionCurrentUser.isAdmin()));
  }

  @PostMapping("/{id}/audit")
  public R<OpinionSource> audit(
      @PathVariable Long id, @Valid @RequestBody SourceAuditRequest request) {
    return R.ok(service.audit(id, request, OpinionCurrentUser.isAdmin()));
  }
}
