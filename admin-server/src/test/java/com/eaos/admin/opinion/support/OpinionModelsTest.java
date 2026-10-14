package com.eaos.admin.opinion.support;

import static org.junit.jupiter.api.Assertions.*;

import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionArticle;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class OpinionModelsTest {
  private final LocalDateTime now = LocalDateTime.of(2026, 10, 11, 12, 0);

  private OpinionArticle article(long id, LocalDateTime time, long source) {
    var row = new OpinionArticle();
    row.setId(id);
    row.setPublishTime(time);
    row.setSourceId(source);
    return row;
  }

  private OpinionAnalysis analysis(int score, String sentiment) {
    var row = new OpinionAnalysis();
    row.setRiskScore(score);
    row.setSentiment(sentiment);
    row.setConfidence(new BigDecimal("0.8"));
    row.setEvidenceIds(List.of("article:1"));
    return row;
  }

  @Test
  void equalWindowsIncludeBoundariesAndExcludeFutureArticles() {
    var rows = List.of(
        article(1, now.minusHours(24), 1),
        article(2, now.minusHours(48), 2),
        article(3, now.minusHours(48).minusSeconds(1), 2),
        article(4, now.plusSeconds(1), 3));
    var trend = OpinionTrendModel.calculate(rows, Map.of(1L, analysis(42, "negative")), now);
    assertEquals(1, trend.currentCount());
    assertEquals(1, trend.previousCount());
    assertEquals(0.0, trend.growthRate());
    assertEquals("stable", trend.direction());
    assertEquals(2, trend.sourceCount());
    assertEquals(1.0 / 3, trend.negativeRatio(), 0.00001);
    assertEquals(1.0 / 24, trend.reportsPerHour(), 0.00001);
    assertEquals(3, trend.timeline().stream().mapToInt(p -> ((Number) p.get("count")).intValue()).sum());
  }

  @Test
  void emptyBaselineIsEmergingNotInfiniteGrowth() {
    var trend = OpinionTrendModel.calculate(List.of(article(1, now, 1)), Map.of(), now);
    assertNull(trend.growthRate());
    assertEquals("emerging", trend.direction());
    var empty = OpinionTrendModel.calculate(List.of(), Map.of(), now);
    assertEquals("stable", empty.direction());
    assertEquals(0, empty.negativeRatio());
  }

  @Test
  void riskThresholdsAndFactorsAreExplainable() {
    assertEquals("关注", OpinionRiskModel.level(39));
    assertEquals("预警", OpinionRiskModel.level(40));
    assertEquals("预警", OpinionRiskModel.level(69));
    assertEquals("危机", OpinionRiskModel.level(70));
    var trend = new OpinionTrendModel.Trend(6, 2, 2.0, "rising", 3, 0.5, 0.25, List.of());
    var risk = OpinionRiskModel.calculate(List.of(analysis(51, "negative")), trend);
    assertEquals(70, risk.score());
    assertEquals("危机", risk.level());
    assertEquals(51, risk.factors().get("severity"));
    assertEquals(5, risk.factors().get("negativeContribution"));
    assertEquals(4, risk.factors().get("sourceContribution"));
    assertEquals(10, risk.factors().get("trendContribution"));
    assertTrue(risk.reviewRequired());
  }

  @Test
  void missingEvidenceAndLowConfidenceRequireReviewEvenAtLowRisk() {
    var trend = OpinionTrendModel.calculate(List.of(), Map.of(), now);
    var row = analysis(5, "neutral");
    assertFalse(OpinionRiskModel.calculate(List.of(row), trend).reviewRequired());
    row.setConfidence(new BigDecimal("0.59"));
    assertTrue(OpinionRiskModel.calculate(List.of(row), trend).reviewRequired());
    row.setConfidence(BigDecimal.ONE);
    row.setEvidenceIds(List.of());
    assertTrue(OpinionRiskModel.calculate(List.of(row), trend).reviewRequired());
    assertTrue(OpinionRiskModel.calculate(List.of(), trend).reviewRequired());
    row.setRiskScore(150);
    assertEquals(100, OpinionRiskModel.calculate(List.of(row), trend).score());
  }
}
