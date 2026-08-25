package com.eaos.admin.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.dto.SourceConfigRequest;
import com.eaos.admin.entity.SourceConfig;
import com.eaos.admin.service.IntelligenceAdminService;
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
import java.util.Map;

@RestController
@RequestMapping("/api/sources")
@RequiredArgsConstructor
public class SourceController {
    private final IntelligenceAdminService service;

    @GetMapping
    public R<List<SourceConfig>> list() { return R.ok(service.listSources()); }

    @PostMapping
    public R<SourceConfig> create(@Valid @RequestBody SourceConfigRequest request) {
        return R.ok(service.saveSource(null, request));
    }

    @PutMapping("/{id}")
    public R<SourceConfig> update(@PathVariable Long id, @Valid @RequestBody SourceConfigRequest request) {
        return R.ok(service.saveSource(id, request));
    }

    @DeleteMapping("/{id}")
    public R<Void> delete(@PathVariable Long id) {
        service.deleteSource(id);
        return R.ok();
    }

    @PostMapping("/{id}/toggle")
    public R<SourceConfig> toggle(@PathVariable Long id) { return R.ok(service.toggle(id)); }

    @PostMapping("/{id}/run")
    public R<Map<String, Object>> run(@PathVariable Long id) { return R.ok(service.trigger(id)); }
}
