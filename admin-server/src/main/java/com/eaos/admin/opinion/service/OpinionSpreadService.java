package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.opinion.config.OpinionServiceProperties;
import com.eaos.admin.opinion.dto.SpreadIngestRequest;
import com.eaos.admin.opinion.entity.OpinionArticle;
import com.eaos.admin.opinion.entity.OpinionSpreadEdge;
import com.eaos.admin.opinion.mapper.OpinionArticleMapper;
import com.eaos.admin.opinion.mapper.OpinionSpreadEdgeMapper;
import com.eaos.admin.opinion.support.InternalTokenVerifier;
import com.eaos.admin.opinion.support.OpinionAuditService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestTemplate;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Slf4j
@Service
@RequiredArgsConstructor
public class OpinionSpreadService {

    private final OpinionArticleMapper articleMapper;
    private final OpinionSpreadEdgeMapper edgeMapper;
    private final RestTemplate restTemplate;
    private final AiServiceProperties aiProperties;
    private final OpinionServiceProperties opinionProperties;
    private final OpinionAuditService auditService;

    /** 传播关系入库（幂等：唯一键 from/to/relation）。验证/推测分字段保存。 */
    @Transactional
    public Map<String, Object> ingest(SpreadIngestRequest request) {
        long stored = 0;
        long skipped = 0;
        for (SpreadIngestRequest.SpreadEdge edge : request.getEdges()) {
            if (edge.getFromArticleId() == null || edge.getToArticleId() == null
                    || edge.getFromArticleId().equals(edge.getToArticleId())) {
                skipped++;
                continue;
            }
            OpinionSpreadEdge existing = edgeMapper.selectOne(Wrappers.<OpinionSpreadEdge>lambdaQuery()
                    .eq(OpinionSpreadEdge::getFromArticleId, edge.getFromArticleId())
                    .eq(OpinionSpreadEdge::getToArticleId, edge.getToArticleId())
                    .eq(OpinionSpreadEdge::getRelationType, edge.getRelationType()));
            if (existing != null) {
                skipped++;
                continue;
            }
            OpinionSpreadEdge entity = new OpinionSpreadEdge();
            entity.setMonitorId(request.getMonitorId());
            entity.setFromArticleId(edge.getFromArticleId());
            entity.setToArticleId(edge.getToArticleId());
            entity.setRelationType(edge.getRelationType());
            entity.setVerified(Boolean.TRUE.equals(edge.getVerified()));
            entity.setEvidence(edge.getEvidence() == null ? "" : edge.getEvidence());
            entity.setConfidence(edge.getConfidence() == null ? BigDecimal.ZERO : edge.getConfidence());
            edgeMapper.insert(entity);
            stored++;
        }
        return Map.of("stored", stored, "skipped", skipped);
    }

    public List<OpinionSpreadEdge> list(Long monitorId, Boolean verified) {
        var wrapper = Wrappers.<OpinionSpreadEdge>lambdaQuery();
        if (monitorId != null) {
            wrapper.eq(OpinionSpreadEdge::getMonitorId, monitorId);
        }
        if (verified != null) {
            wrapper.eq(OpinionSpreadEdge::getVerified, verified);
        }
        return edgeMapper.selectList(wrapper.orderByDesc(OpinionSpreadEdge::getCreatedAt));
    }

    /** 调用 Python 分析传播关系（相似度/时间/引用线索），结果落库。 */
    public Map<String, Object> analyze(Long monitorId) {
        List<OpinionArticle> articles = articleMapper.selectList(Wrappers.<OpinionArticle>lambdaQuery()
                .eq(OpinionArticle::getMonitorId, monitorId)
                .eq(OpinionArticle::getStatus, "analyzed")
                .orderByDesc(OpinionArticle::getCollectedAt)
                .last("LIMIT 50"));
        if (articles.size() < 2) {
            return Map.of("stored", 0L, "reason", "样本不足");
        }
        List<Map<String, Object>> items = new ArrayList<>();
        for (OpinionArticle article : articles) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", article.getId());
            item.put("title", article.getTitle());
            item.put("content", article.getContent().length() > 4000 ? article.getContent().substring(0, 4000) : article.getContent());
            item.put("url", article.getUrl());
            item.put("sourceId", article.getSourceId());
            item.put("publishTime", String.valueOf(
                    article.getPublishTime() == null ? article.getCollectedAt() : article.getPublishTime()));
            items.add(item);
        }
        String base = aiProperties.getBaseUrl();
        String url = base + "/internal/opinion/spread/analyze";
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set(InternalTokenVerifier.HEADER, opinionProperties.getInternalToken());
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("monitorId", monitorId);
        body.put("articles", items);
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> response = restTemplate.postForObject(url, new HttpEntity<>(body, headers), Map.class);
            List<Map<String, Object>> edges = response == null ? List.of()
                    : castList(response.get("edges"));
            SpreadIngestRequest ingestRequest = new SpreadIngestRequest();
            ingestRequest.setMonitorId(monitorId);
            List<SpreadIngestRequest.SpreadEdge> edgeList = new ArrayList<>();
            for (Map<String, Object> edge : edges) {
                SpreadIngestRequest.SpreadEdge e = new SpreadIngestRequest.SpreadEdge();
                e.setFromArticleId(longValue(edge.get("fromArticleId")));
                e.setToArticleId(longValue(edge.get("toArticleId")));
                e.setRelationType(String.valueOf(edge.getOrDefault("relationType", "相似")));
                e.setVerified(Boolean.TRUE.equals(edge.get("verified")));
                e.setEvidence(String.valueOf(edge.getOrDefault("evidence", "")));
                e.setConfidence(decimal(edge.get("confidence")));
                edgeList.add(e);
            }
            ingestRequest.setEdges(edgeList);
            Map<String, Object> result = ingest(ingestRequest);
            auditService.record("SPREAD_ANALYZE", "opinion_spread_edge", monitorId,
                    Map.of("analyzed", (long) articles.size()), null);
            return result;
        } catch (Exception e) {
            log.warn("传播分析失败 monitorId={}: {}", monitorId, e.getMessage());
            return Map.of("stored", 0L, "error", e.getMessage());
        }
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> castList(Object value) {
        return value instanceof List ? (List<Map<String, Object>>) value : List.of();
    }

    private Long longValue(Object value) {
        return value instanceof Number ? ((Number) value).longValue() : null;
    }

    private BigDecimal decimal(Object value) {
        if (value instanceof Number) {
            return BigDecimal.valueOf(((Number) value).doubleValue());
        }
        return BigDecimal.ZERO;
    }
}
