package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.entity.OpinionSpreadEdge;
import com.eaos.admin.opinion.service.OpinionSpreadService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/opinion/spread")
@RequiredArgsConstructor
public class OpinionSpreadController {

    private final OpinionSpreadService service;

    @GetMapping
    public R<List<OpinionSpreadEdge>> list(@RequestParam(required = false) Long monitorId,
                                           @RequestParam(required = false) Boolean verified) {
        return R.ok(service.list(monitorId, verified));
    }

    @PostMapping("/analyze")
    public R<Map<String, Object>> analyze(@RequestParam Long monitorId) {
        return R.ok(service.analyze(monitorId));
    }
}
