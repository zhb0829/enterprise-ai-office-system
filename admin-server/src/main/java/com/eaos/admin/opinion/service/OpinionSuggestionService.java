package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.opinion.config.OpinionServiceProperties;
import com.eaos.admin.opinion.dto.SuggestionFeedbackRequest;
import com.eaos.admin.opinion.entity.OpinionAlertEvent;
import com.eaos.admin.opinion.entity.OpinionEvent;
import com.eaos.admin.opinion.entity.OpinionMonitor;
import com.eaos.admin.opinion.entity.OpinionResponseCase;
import com.eaos.admin.opinion.entity.OpinionSuggestion;
import com.eaos.admin.opinion.mapper.OpinionAlertEventMapper;
import com.eaos.admin.opinion.mapper.OpinionEventMapper;
import com.eaos.admin.opinion.mapper.OpinionMonitorMapper;
import com.eaos.admin.opinion.mapper.OpinionResponseCaseMapper;
import com.eaos.admin.opinion.mapper.OpinionSuggestionMapper;
import com.eaos.admin.opinion.support.InternalTokenVerifier;
import com.eaos.admin.opinion.support.OpinionAuditService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class OpinionSuggestionService {

    private final OpinionSuggestionMapper suggestionMapper;
    private final OpinionAlertEventMapper alertEventMapper;
    private final OpinionEventMapper eventMapper;
    private final OpinionMonitorMapper monitorMapper;
    private final OpinionResponseCaseMapper responseCaseMapper;
    private final RestTemplate restTemplate;
    private final AiServiceProperties aiProperties;
    private final OpinionServiceProperties opinionProperties;
    private final OpinionAuditService auditService;

    /** 基于历史案例 RAG 生成应对建议（默认需人工确认）。 */
    @Transactional
    public OpinionSuggestion generate(String targetType, Long targetId) {
        OpinionSuggestion pending = suggestionMapper.selectOne(Wrappers.<OpinionSuggestion>lambdaQuery()
                .eq(OpinionSuggestion::getTargetType, targetType)
                .eq(OpinionSuggestion::getTargetId, targetId)
                .eq(OpinionSuggestion::getStatus, "pending")
                .orderByDesc(OpinionSuggestion::getCreatedAt)
                .last("LIMIT 1"));
        if (pending != null && !needsRefresh(pending)) {
            return pending;
        }
        Map<String, Object> context = buildContext(targetType, targetId);
        Long monitorId = context.get("monitorId") == null ? null : ((Number) context.get("monitorId")).longValue();
        String base = aiProperties.getBaseUrl();
        String url = base + "/internal/opinion/suggestions/generate";
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set(InternalTokenVerifier.HEADER, opinionProperties.getInternalToken());
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("targetType", targetType);
        body.put("targetId", targetId);
        body.put("monitorId", monitorId);
        body.put("context", context);
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> response = restTemplate.postForObject(url, new HttpEntity<>(body, headers), Map.class);
            if (response == null) {
                throw new IllegalArgumentException("应对建议生成接口无返回");
            }
            OpinionSuggestion suggestion = pending == null ? new OpinionSuggestion() : pending;
            if (pending == null) {
                suggestion.setTargetType(targetType);
                suggestion.setTargetId(targetId);
                suggestion.setMonitorId(monitorId);
                suggestion.setCreatedBy(OpinionCurrentUser.username());
            }
            suggestion.setContent(String.valueOf(response.getOrDefault("content", "")));
            suggestion.setCitations(enrichCitations(castList(response.get("citations"))));
            suggestion.setModel(String.valueOf(response.getOrDefault("model", "")));
            suggestion.setPromptVersion(String.valueOf(response.getOrDefault("promptVersion", "")));
            suggestion.setStatus("pending");
            if (pending == null) {
                suggestionMapper.insert(suggestion);
            } else {
                suggestionMapper.updateById(suggestion);
            }
            auditService.record(pending == null ? "SUGGESTION_GENERATE" : "SUGGESTION_REFRESH", "opinion_suggestion", suggestion.getId(),
                    Map.of("targetType", targetType, "targetId", targetId), null);
            return suggestion;
        } catch (Exception e) {
            log.error("应对建议生成失败 target={}:{}: {}", targetType, targetId, e.getMessage());
            throw new IllegalArgumentException("应对建议生成失败：" + e.getMessage());
        }
    }

    public OpinionSuggestion feedback(Long id, SuggestionFeedbackRequest request) {
        OpinionSuggestion suggestion = suggestionMapper.selectById(id);
        if (suggestion == null) {
            throw new IllegalArgumentException("应对建议不存在");
        }
        suggestion.setStatus(request.getStatus());
        suggestion.setFeedback(request.getFeedback());
        suggestionMapper.updateById(suggestion);
        auditService.record("SUGGESTION_FEEDBACK", "opinion_suggestion", id,
                Map.of("status", request.getStatus(), "feedback", request.getFeedback()), null);
        return suggestion;
    }

    public List<OpinionSuggestion> list(String targetType, Long targetId) {
        var wrapper = Wrappers.<OpinionSuggestion>lambdaQuery();
        if (targetType != null && !targetType.isBlank()) {
            wrapper.eq(OpinionSuggestion::getTargetType, targetType);
        }
        if (targetId != null) {
            wrapper.eq(OpinionSuggestion::getTargetId, targetId);
        }
        return suggestionMapper.selectList(wrapper.orderByDesc(OpinionSuggestion::getCreatedAt));
    }

    private Map<String, Object> buildContext(String targetType, Long targetId) {
        Map<String, Object> context = new LinkedHashMap<>();
        if ("alert".equals(targetType)) {
            OpinionAlertEvent alert = alertEventMapper.selectById(targetId);
            if (alert == null) {
                throw new IllegalArgumentException("告警事件不存在");
            }
            context.put("monitorId", alert.getMonitorId());
            context.put("riskLevel", alert.getRiskLevel());
            context.put("triggerStats", alert.getTriggerStats());
            OpinionMonitor monitor = alert.getMonitorId() == null ? null : monitorMapper.selectById(alert.getMonitorId());
            context.put("monitorName", monitor == null ? "" : monitor.getName());
            OpinionEvent event = alert.getEventId() == null
                    ? eventMapper.selectOne(Wrappers.<OpinionEvent>lambdaQuery()
                    .eq(OpinionEvent::getMonitorId, alert.getMonitorId())
                    .orderByDesc(OpinionEvent::getUpdatedAt)
                    .last("LIMIT 1"))
                    : eventMapper.selectById(alert.getEventId());
            if (event != null) {
                context.put("eventId", event.getId());
                context.put("title", event.getTitle());
                context.put("summary", event.getSummary());
                context.put("keywords", event.getKeywords());
                context.put("reportCount", event.getReportCount());
                context.put("spreadSpeed", event.getSpreadSpeed());
            }
        } else if ("event".equals(targetType)) {
            OpinionEvent event = eventMapper.selectById(targetId);
            if (event == null) {
                throw new IllegalArgumentException("热点事件不存在");
            }
            context.put("monitorId", event.getMonitorId());
            context.put("title", event.getTitle());
            context.put("summary", event.getSummary());
            context.put("riskLevel", event.getRiskLevel());
            context.put("sentimentDist", event.getSentimentDist());
            context.put("reportCount", event.getReportCount());
            context.put("spreadSpeed", event.getSpreadSpeed());
        } else {
            throw new IllegalArgumentException("不支持的生成目标类型：" + targetType);
        }
        return context;
    }

    @SuppressWarnings("unchecked")
    private List<Object> castList(Object value) {
        return value instanceof List ? (List<Object>) value : List.of();
    }

    private List<Object> enrichCitations(List<Object> citations) {
        List<Object> enriched = new ArrayList<>();
        for (Object citation : citations) {
            if (!(citation instanceof Map<?, ?> raw)) {
                enriched.add(citation);
                continue;
            }
            Map<String, Object> item = new LinkedHashMap<>();
            raw.forEach((key, value) -> item.put(String.valueOf(key), value));
            Long caseId = toLong(item.get("caseId"));
            String title = String.valueOf(item.getOrDefault("title", "")).trim();
            if (caseId != null && title.isBlank()) {
                OpinionResponseCase responseCase = responseCaseMapper.selectById(caseId);
                if (responseCase != null) {
                    item.put("title", responseCase.getTitle());
                }
            }
            enriched.add(item);
        }
        return enriched;
    }

    private Long toLong(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        try {
            return value == null ? null : Long.valueOf(String.valueOf(value));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private boolean needsRefresh(OpinionSuggestion suggestion) {
        if ((suggestion.getCitations() == null || suggestion.getCitations().isEmpty())
                && suggestion.getContent() != null
                && suggestion.getContent().contains("暂未检索到足够相似")) {
            return true;
        }
        if (suggestion.getCitations() == null || suggestion.getCitations().isEmpty()) {
            return false;
        }
        return suggestion.getCitations().stream()
                .filter(Map.class::isInstance)
                .map(Map.class::cast)
                .noneMatch(citation -> citation.get("title") != null
                        && !String.valueOf(citation.get("title")).isBlank());
    }
}
