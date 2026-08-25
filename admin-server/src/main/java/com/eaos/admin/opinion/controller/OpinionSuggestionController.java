package com.eaos.admin.opinion.controller;

import com.eaos.admin.common.R;
import com.eaos.admin.opinion.dto.SuggestionFeedbackRequest;
import com.eaos.admin.opinion.entity.OpinionSuggestion;
import com.eaos.admin.opinion.service.OpinionSuggestionService;
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
@RequestMapping("/api/opinion/suggestions")
@RequiredArgsConstructor
public class OpinionSuggestionController {

    private final OpinionSuggestionService service;

    @GetMapping
    public R<List<OpinionSuggestion>> list(@RequestParam(required = false) String targetType,
                                           @RequestParam(required = false) Long targetId) {
        return R.ok(service.list(targetType, targetId));
    }

    @PostMapping("/generate")
    public R<OpinionSuggestion> generate(@RequestParam String targetType,
                                         @RequestParam Long targetId) {
        return R.ok(service.generate(targetType, targetId));
    }

    @PostMapping("/{id}/feedback")
    public R<OpinionSuggestion> feedback(@PathVariable Long id,
                                         @Valid @RequestBody SuggestionFeedbackRequest request) {
        return R.ok(service.feedback(id, request));
    }
}
