package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.entity.OpinionEvent;
import com.eaos.admin.opinion.service.OpinionEventService;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/opinion/events")
@RequiredArgsConstructor
public class OpinionEventController {

    private final OpinionEventService service;

    @GetMapping
    public R<List<OpinionEvent>> list(@RequestParam(required = false) Long monitorId,
                                      @RequestParam(required = false) String riskLevel) {
        return R.ok(service.list(monitorId, riskLevel));
    }

    @PostMapping("/{monitorId}/aggregate")
    public R<Void> aggregate(@PathVariable Long monitorId) {
        service.aggregate(monitorId);
        return R.ok();
    }
}
