package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.opinion.config.OpinionServiceProperties;
import com.eaos.admin.opinion.dto.ResponseCaseRequest;
import com.eaos.admin.opinion.entity.OpinionResponseCase;
import com.eaos.admin.opinion.mapper.OpinionResponseCaseMapper;
import com.eaos.admin.opinion.support.InternalTokenVerifier;
import com.eaos.admin.opinion.support.OpinionAuditService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class OpinionResponseCaseService {

    private final OpinionResponseCaseMapper caseMapper;
    private final OpinionAuditService auditService;
    private final RestTemplate restTemplate;
    private final AiServiceProperties aiProperties;
    private final OpinionServiceProperties opinionProperties;

    public List<OpinionResponseCase> list(String eventType, String riskLevel, String keyword) {
        var wrapper = Wrappers.<OpinionResponseCase>lambdaQuery();
        if (eventType != null && !eventType.isBlank()) {
            wrapper.eq(OpinionResponseCase::getEventType, eventType);
        }
        if (riskLevel != null && !riskLevel.isBlank()) {
            wrapper.eq(OpinionResponseCase::getRiskLevel, riskLevel);
        }
        if (keyword != null && !keyword.isBlank()) {
            wrapper.and(w -> w.like(OpinionResponseCase::getTitle, keyword)
                    .or().like(OpinionResponseCase::getContent, keyword));
        }
        return caseMapper.selectList(wrapper.orderByDesc(OpinionResponseCase::getCreatedAt));
    }

    public List<OpinionResponseCase> listAll() {
        return caseMapper.selectList(Wrappers.<OpinionResponseCase>lambdaQuery().orderByDesc(OpinionResponseCase::getId));
    }

    /** 触发 Python 重建案例向量索引。 */
    public Map<String, Object> reindex() {
        String url = aiProperties.getBaseUrl() + "/internal/opinion/cases/reindex";
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set(InternalTokenVerifier.HEADER, opinionProperties.getInternalToken());
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> response = restTemplate.postForObject(url, new HttpEntity<>(Map.of(), headers), Map.class);
            if (response == null) {
                throw new IllegalArgumentException("案例索引重建接口无返回");
            }
            auditService.record("CASE_REINDEX", "opinion_response_case", null,
                    Map.of("chunks", response.get("chunks")), null);
            return response;
        } catch (Exception e) {
            log.error("案例索引重建失败: {}", e.getMessage());
            throw new IllegalArgumentException("案例索引重建失败：" + e.getMessage());
        }
    }

    public OpinionResponseCase create(ResponseCaseRequest request) {
        OpinionResponseCase entity = new OpinionResponseCase();
        apply(entity, request);
        entity.setCreatedBy(OpinionCurrentUser.username());
        caseMapper.insert(entity);
        auditService.record("CASE_CREATE", "opinion_response_case", entity.getId(),
                Map.of("title", entity.getTitle()), null);
        return entity;
    }

    public OpinionResponseCase update(Long id, ResponseCaseRequest request) {
        OpinionResponseCase entity = caseMapper.selectById(id);
        if (entity == null) {
            throw new IllegalArgumentException("案例不存在");
        }
        apply(entity, request);
        entity.setUpdatedAt(LocalDateTime.now());
        caseMapper.updateById(entity);
        return entity;
    }

    public void delete(Long id) {
        if (caseMapper.deleteById(id) == 0) {
            throw new IllegalArgumentException("案例不存在");
        }
        auditService.record("CASE_DELETE", "opinion_response_case", id, Map.of(), null);
    }

    private void apply(OpinionResponseCase entity, ResponseCaseRequest request) {
        entity.setTitle(request.getTitle().trim());
        entity.setEventType(nvl(request.getEventType()));
        entity.setRiskLevel(nvl(request.getRiskLevel()));
        entity.setStrategy(nvl(request.getStrategy()));
        entity.setContent(nvl(request.getContent()));
        entity.setEffect(nvl(request.getEffect()));
        entity.setTags(request.getTags() == null ? List.of() : request.getTags());
        entity.setSource(nvl(request.getSource()));
    }

    private static String nvl(String value) {
        return value == null ? "" : value.trim();
    }
}
