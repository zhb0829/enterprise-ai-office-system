package com.eaos.admin.opinion.support;

import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionArticle;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/** Equal-length windows; growth is undefined when the baseline is empty. */
public final class OpinionTrendModel {
  private OpinionTrendModel() {}

  public record Trend(int currentCount, int previousCount, Double growthRate, String direction,
      int sourceCount, double negativeRatio, double reportsPerHour,
      List<Map<String, Object>> timeline) {}

  public static LocalDateTime articleTime(OpinionArticle article, LocalDateTime fallback) {
    if (article.getPublishTime() != null) return article.getPublishTime();
    if (article.getCollectedAt() != null) return article.getCollectedAt();
    return article.getCreatedAt() != null ? article.getCreatedAt() : fallback;
  }

  public static Trend calculate(
      List<OpinionArticle> articles, Map<Long, OpinionAnalysis> analyses, LocalDateTime now) {
    int current = 0, previous = 0, negative = 0, observed = 0;
    Map<LocalDateTime, List<OpinionArticle>> buckets = new TreeMap<>();
    for (OpinionArticle article : articles) {
      LocalDateTime time = articleTime(article, now);
      if (time.isAfter(now)) continue;
      observed++;
      OpinionAnalysis analysis = analyses.get(article.getId());
      if (analysis != null && "negative".equals(analysis.getSentiment())) negative++;
      if (!time.isBefore(now.minusHours(24))) current++;
      else if (!time.isBefore(now.minusHours(48))) previous++;
      buckets.computeIfAbsent(time.truncatedTo(ChronoUnit.HOURS), key -> new ArrayList<>()).add(article);
    }
    List<Map<String, Object>> timeline = new ArrayList<>();
    for (var entry : buckets.entrySet()) {
      List<OpinionArticle> rows = entry.getValue();
      long negatives = rows.stream().filter(a -> analyses.containsKey(a.getId())
          && "negative".equals(analyses.get(a.getId()).getSentiment())).count();
      Map<String, Object> point = new LinkedHashMap<>();
      point.put("time", entry.getKey().toString());
      point.put("count", rows.size());
      point.put("negativeCount", negatives);
      point.put("sourceCount", rows.stream().map(OpinionArticle::getSourceId).filter(java.util.Objects::nonNull).distinct().count());
      point.put("maxRiskScore", rows.stream().map(a -> analyses.get(a.getId()))
          .filter(java.util.Objects::nonNull).map(OpinionAnalysis::getRiskScore)
          .filter(java.util.Objects::nonNull).mapToInt(Integer::intValue).max().orElse(0));
      timeline.add(point);
    }
    int sources = (int) articles.stream().filter(a -> !articleTime(a, now).isAfter(now))
        .map(OpinionArticle::getSourceId).filter(java.util.Objects::nonNull).distinct().count();
    Double growth = previous == 0 ? null : (double) (current - previous) / previous;
    String direction = previous == 0 ? (current > 0 ? "emerging" : "stable")
        : growth > 0.2 ? "rising" : growth < -0.2 ? "falling" : "stable";
    return new Trend(current, previous, growth, direction, sources,
        observed == 0 ? 0 : (double) negative / observed, current / 24.0, timeline);
  }
}
