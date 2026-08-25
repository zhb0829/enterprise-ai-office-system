package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.dto.AlertHandleRequest;
import com.eaos.admin.opinion.entity.OpinionAlertEvent;
import com.eaos.admin.opinion.entity.OpinionNotification;
import com.eaos.admin.opinion.service.OpinionAlertService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/opinion/alerts")
@RequiredArgsConstructor
public class OpinionAlertController {

    private final OpinionAlertService service;

    @GetMapping
    public R<List<OpinionAlertEvent>> list(@RequestParam(required = false) Long monitorId,
                                           @RequestParam(required = false) String state) {
        return R.ok(service.list(monitorId, state));
    }

    @GetMapping("/{id}")
    public R<OpinionAlertEvent> get(@PathVariable Long id) {
        return R.ok(service.get(id));
    }

    @PostMapping("/{id}/handle")
    public R<OpinionAlertEvent> handle(@PathVariable Long id, @Valid @RequestBody AlertHandleRequest request) {
        return R.ok(service.handle(id, request));
    }

    @GetMapping("/{id}/notifications")
    public R<List<OpinionNotification>> notifications(@PathVariable Long id) {
        return R.ok(service.notifications(id));
    }
}
