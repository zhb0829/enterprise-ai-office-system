package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionArticle;
import com.eaos.admin.opinion.entity.OpinionEvent;
import com.eaos.admin.opinion.mapper.OpinionAnalysisMapper;
import com.eaos.admin.opinion.mapper.OpinionArticleMapper;
import com.eaos.admin.opinion.mapper.OpinionEventMapper;
import com.eaos.admin.opinion.support.OpinionAccessService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

@Service
@RequiredArgsConstructor
public class OpinionEventService {

    private final OpinionEventMapper eventMapper;
    private final OpinionAnalysisMapper analysisMapper;
    private final OpinionArticleMapper articleMapper;
    private final OpinionAccessService accessService;

    /** 按 AI 主题将已分析文章聚合为事件。幂等：事件以 (monitor_id, title) 为键。 */
    @Transactional
    public void aggregate(Long monitorId) {
        accessService.requireMonitor(monitorId);
        List<OpinionArticle> articles = articleMapper.selectList(Wrappers.<OpinionArticle>lambdaQuery()
                .eq(OpinionArticle::getMonitorId, monitorId)
                .eq(OpinionArticle::getStatus, "analyzed")
                .orderByAsc(OpinionArticle::getId));
        if (articles.isEmpty()) {
            return;
        }
        List<Long> ids = articles.stream().map(OpinionArticle::getId).toList();
        List<OpinionAnalysis> analyses = analysisMapper.selectList(Wrappers.<OpinionAnalysis>lambdaQuery()
                .in(OpinionAnalysis::getArticleId, ids)
                .orderByDesc(OpinionAnalysis::getVersion));
        Map<Long, OpinionAnalysis> latest = new LinkedHashMap<>();
        for (OpinionAnalysis analysis : analyses) {
            latest.putIfAbsent(analysis.getArticleId(), analysis);
        }

        Map<String, Set<Long>> groups = new LinkedHashMap<>();
        for (OpinionArticle article : articles) {
            OpinionAnalysis analysis = latest.get(article.getId());
            String topic = analysis == null ? "" : analysis.getTopic();
            if (topic == null || topic.isBlank()) {
                topic = article.getMatchedKeywords() != null && !article.getMatchedKeywords().isEmpty()
                        ? article.getMatchedKeywords().get(0) : "未命名主题";
            }
            groups.computeIfAbsent(topic, k -> new LinkedHashSet<>()).add(article.getId());
        }

        for (Map.Entry<String, Set<Long>> entry : groups.entrySet()) {
            String topic = entry.getKey();
            Set<Long> articleIds = entry.getValue();
            OpinionEvent event = eventMapper.selectOne(Wrappers.<OpinionEvent>lambdaQuery()
                    .eq(OpinionEvent::getMonitorId, monitorId)
                    .eq(OpinionEvent::getTitle, topic));
            if (event == null) {
                event = new OpinionEvent();
                event.setMonitorId(monitorId);
                event.setTitle(topic);
                event.setStatus("active");
                event.setVersion(1);
            }
            List<OpinionArticle> rows = articleMapper.selectBatchIds(articleIds);
            List<OpinionArticle> sorted = new ArrayList<>(rows);
            sorted.sort((a, b) -> a.getCollectedAt().compareTo(b.getCollectedAt()));

            LocalDateTime start = sorted.isEmpty() ? LocalDateTime.now() : sorted.get(0).getCollectedAt();
            LocalDateTime end = sorted.isEmpty() ? LocalDateTime.now() : sorted.get(rows.size() - 1).getCollectedAt();
            int positive = 0;
            int neutral = 0;
            int negative = 0;
            int riskMax = 0;
            Set<String> sources = new LinkedHashSet<>();
            List<String> keywords = new ArrayList<>();
            List<Long> newArticleIds = new ArrayList<>(articleIds);
            for (OpinionArticle row : sorted) {
                OpinionAnalysis analysis = latest.get(row.getId());
                if (analysis == null) {
                    neutral++;
                    continue;
                }
                switch (analysis.getSentiment()) {
                    case "positive" -> positive++;
                    case "negative" -> negative++;
                    default -> neutral++;
                }
                if (analysis.getRiskScore() != null) {
                    riskMax = Math.max(riskMax, analysis.getRiskScore());
                }
                if (row.getSourceId() != null) {
                    sources.add(String.valueOf(row.getSourceId()));
                }
                if (analysis.getKeywords() != null) {
                    keywords.addAll(analysis.getKeywords());
                }
            }
            event.setArticleIds(newArticleIds);
            event.setSentimentDist(Map.of(
                    "positive", positive, "neutral", neutral, "negative", negative));
            event.setReportCount(rows.size());
            event.setTimeStart(start);
            event.setTimeEnd(end);
            event.setSourceWeight(new BigDecimal(sources.size()));
            event.setSpreadSpeed(sources.size());
            event.setKeywords(keywords.stream().distinct().limit(10).toList());
            event.setRiskLevel(riskLevel(riskMax));
            event.setSummary("共聚合 " + rows.size() + " 篇相关文章，来源 " + sources.size() + " 个。");
            event.setUpdatedAt(LocalDateTime.now());
            if (event.getId() == null) {
                eventMapper.insert(event);
            } else {
                eventMapper.updateById(event);
            }
        }
    }

    private String riskLevel(int score) {
        if (score >= 70) {
            return "危机";
        }
        if (score >= 40) {
            return "预警";
        }
        return "关注";
    }

    public List<OpinionEvent> list(Long monitorId, String riskLevel) {
        var wrapper = Wrappers.<OpinionEvent>lambdaQuery();
        if (monitorId != null) {
            accessService.requireMonitor(monitorId);
            wrapper.eq(OpinionEvent::getMonitorId, monitorId);
        } else if (com.eaos.admin.opinion.support.OpinionCurrentUser.isAuthenticated()
                && !com.eaos.admin.opinion.support.OpinionCurrentUser.isAdmin()) {
            var ids = accessService.visibleMonitorIds();
            if (ids.isEmpty()) {
                return List.of();
            }
            wrapper.in(OpinionEvent::getMonitorId, ids);
        }
        if (riskLevel != null && !riskLevel.isBlank()) {
            wrapper.eq(OpinionEvent::getRiskLevel, riskLevel);
        }
        return eventMapper.selectList(wrapper.orderByDesc(OpinionEvent::getRiskLevel)
                .orderByDesc(OpinionEvent::getReportCount));
    }
}
