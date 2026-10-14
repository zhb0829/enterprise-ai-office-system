package com.eaos.admin.opinion.support;

import com.eaos.admin.opinion.entity.OpinionAnalysis;
import java.math.BigDecimal;
import java.util.Collection;
import java.util.Map;

/** Explainable screening, not a factual determination of wrongdoing. */
public final class OpinionRiskModel {
  public static final String VERSION = "opinion-risk-v1";
  private OpinionRiskModel() {}

  public record Risk(int score, String level, boolean reviewRequired, Map<String, Object> factors) {}

  public static String level(int score) {
    return score >= 70 ? "危机" : score >= 40 ? "预警" : "关注";
  }

  public static Risk calculate(Collection<OpinionAnalysis> analyses, OpinionTrendModel.Trend trend) {
    int severity = analyses.stream().map(OpinionAnalysis::getRiskScore)
        .filter(java.util.Objects::nonNull).mapToInt(v -> Math.max(0, Math.min(100, v))).max().orElse(0);
    int negative = (int) Math.round(trend.negativeRatio() * 10);
    int diversity = Math.min(10, Math.max(0, trend.sourceCount() - 1) * 2);
    int acceleration = "rising".equals(trend.direction()) ? 10 : 0;
    int score = Math.min(100, severity + negative + diversity + acceleration);
    boolean uncertain = analyses.isEmpty() || analyses.stream().anyMatch(a ->
        a.getConfidence() == null || a.getConfidence().compareTo(new BigDecimal("0.6")) < 0
        || a.getEvidenceIds() == null || a.getEvidenceIds().isEmpty());
    return new Risk(score, level(score), score >= 40 || uncertain,
        Map.of("severity", severity, "negativeContribution", negative,
            "sourceContribution", diversity, "trendContribution", acceleration,
            "lowConfidenceOrMissingEvidence", uncertain, "modelVersion", VERSION));
  }
}
