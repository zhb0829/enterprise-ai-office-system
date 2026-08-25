package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.entity.OpinionReport;
import com.eaos.admin.opinion.service.OpinionReportService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/opinion/reports")
@RequiredArgsConstructor
public class OpinionReportController {

    private final OpinionReportService service;

    @GetMapping
    public R<List<OpinionReport>> list(@RequestParam(required = false) Long monitorId,
                                       @RequestParam(required = false) String period) {
        return R.ok(service.list(monitorId, period));
    }

    @GetMapping("/{id}")
    public R<OpinionReport> get(@PathVariable Long id) {
        return R.ok(service.get(id));
    }

    @PostMapping("/generate")
    public R<OpinionReport> generate(@RequestParam Long monitorId,
                                     @RequestParam(defaultValue = "daily") String period) {
        return R.ok(service.generate(monitorId, period));
    }

    @PostMapping("/{id}/publish")
    public R<OpinionReport> publish(@PathVariable Long id) {
        return R.ok(service.publish(id));
    }

    @GetMapping("/{id}/pdf")
    public R<Map<String, Object>> pdf(@PathVariable Long id) {
        return R.ok(service.exportPdf(id));
    }
}
