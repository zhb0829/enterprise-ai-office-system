package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.dto.OpinionMonitorRequest;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import com.eaos.admin.opinion.service.OpinionMonitorService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/opinion/monitors")
@RequiredArgsConstructor
public class OpinionMonitorController {

    private final OpinionMonitorService service;

    @GetMapping
    public R<List<OpinionMonitor>> list() {
        return R.ok(service.list());
    }

    @GetMapping("/{id}")
    public R<OpinionMonitor> get(@PathVariable Long id) {
        return R.ok(service.get(id));
    }

    @PostMapping
    public R<OpinionMonitor> create(@Valid @RequestBody OpinionMonitorRequest request) {
        return R.ok(service.create(request));
    }

    @PutMapping("/{id}")
    public R<OpinionMonitor> update(@PathVariable Long id, @Valid @RequestBody OpinionMonitorRequest request) {
        return R.ok(service.update(id, request));
    }

    @DeleteMapping("/{id}")
    public R<Void> delete(@PathVariable Long id) {
        service.delete(id);
        return R.ok();
    }

    @PostMapping("/{id}/toggle")
    public R<OpinionMonitor> toggle(@PathVariable Long id) {
        return R.ok(service.toggle(id));
    }
}
