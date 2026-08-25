package com.eaos.admin.opinion.support;

import com.eaos.admin.opinion.entity.OpinionMonitor;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class OpinionTextTest {

    @Test
    void anyMatch_returnsAllMatchedWords() {
        OpinionMonitor monitor = new OpinionMonitor();
        monitor.setMatchMode("any");
        monitor.setBrandWords(List.of("某科技", "AI"));
        monitor.setCompetitorWords(List.of());
        monitor.setExecutiveNames(List.of());
        monitor.setExcludeWords(List.of());

        List<String> matched = OpinionText.matchKeywords(monitor, "某科技发布企业 AI 助手", "研发新一代产品");
        assertTrue(matched.contains("某科技"));
        assertTrue(matched.contains("AI"));
    }

    @Test
    void excludeWords_alwaysReject() {
        OpinionMonitor monitor = new OpinionMonitor();
        monitor.setMatchMode("any");
        monitor.setBrandWords(List.of("某科技"));
        monitor.setExcludeWords(List.of("不实"));

        assertTrue(OpinionText.matchKeywords(monitor, "某科技涉嫌违规", "网传不实事件").isEmpty());
    }

    @Test
    void allMatch_requiresEveryPositiveTerm() {
        OpinionMonitor monitor = new OpinionMonitor();
        monitor.setMatchMode("all");
        monitor.setBrandWords(List.of("某科技", "AI"));
        monitor.setExcludeWords(List.of());

        assertTrue(OpinionText.matchKeywords(monitor, "某科技发布新品", "正文只提到公司").isEmpty());
        assertEquals(2, OpinionText.matchKeywords(monitor, "某科技发布 AI 产品", "正文提到某科技与AI").size());
    }

    @Test
    void nullWordLists_areTreatedAsEmpty() {
        OpinionMonitor monitor = new OpinionMonitor();
        monitor.setMatchMode("any");
        assertTrue(OpinionText.matchKeywords(monitor, "任意标题", "任意正文").isEmpty());
    }

    @Test
    void contentHash_isStableAndUrlNormalizedForDedupe() {
        String a = OpinionText.contentHash("行业趋势", "正文内容", "https://EXAMPLE.com/?utm_source=x");
        String b = OpinionText.contentHash("行业趋势", "正文内容", "https://example.com/");
        assertEquals(a, b);
        assertNotEquals(a, OpinionText.contentHash("别的标题", "正文内容", "https://example.com/"));
    }
}
