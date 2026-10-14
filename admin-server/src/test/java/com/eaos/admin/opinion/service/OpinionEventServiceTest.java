package com.eaos.admin.opinion.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.eaos.admin.opinion.entity.*;
import com.eaos.admin.opinion.mapper.*;
import com.eaos.admin.opinion.support.OpinionAccessService;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class OpinionEventServiceTest {
  @Mock OpinionEventMapper eventMapper;
  @Mock OpinionAnalysisMapper analysisMapper;
  @Mock OpinionArticleMapper articleMapper;
  @Mock OpinionAccessService accessService;
  @InjectMocks OpinionEventService service;

  private OpinionArticle article(long id) {
    var row = new OpinionArticle();
    row.setId(id);
    row.setMonitorId(1L);
    row.setPublishTime(LocalDateTime.now().minusHours(1));
    row.setTitle("article " + id);
    row.setSourceId(id);
    return row;
  }

  private OpinionAnalysis analysis(long articleId, int version, String status, List<String> subjects) {
    var row = new OpinionAnalysis();
    row.setArticleId(articleId);
    row.setVersion(version);
    row.setStatus(status);
    row.setSubjects(subjects);
    row.setEventType("quality");
    row.setSentiment("negative");
    row.setRiskScore(40);
    row.setConfidence(BigDecimal.ONE);
    row.setEvidenceIds(List.of("article:" + articleId));
    return row;
  }

  @Test
  void latestRejectedAnalysisIsNotReplacedByOlderAiResult() {
    when(articleMapper.selectList(any())).thenReturn(List.of(article(1)));
    when(analysisMapper.selectList(any())).thenReturn(List.of(
        analysis(1, 2, "rejected", List.of("Company")),
        analysis(1, 1, "pending", List.of("Company"))));
    var existing = new OpinionEvent();
    existing.setId(7L);
    existing.setEventKey("old-event");
    existing.setStatus("active");
    when(eventMapper.selectList(any())).thenReturn(List.of(existing));
    service.aggregate(1L);
    verify(eventMapper).lockMonitor(1L);
    verify(eventMapper).updateById(existing);
    verify(eventMapper, never()).insert(any(OpinionEvent.class));
    assertEquals("superseded", existing.getStatus());
  }

  @Test
  void unidentifiedSubjectsDoNotMergeUnrelatedArticles() {
    when(articleMapper.selectList(any())).thenReturn(List.of(article(1), article(2)));
    when(analysisMapper.selectList(any())).thenReturn(List.of(
        analysis(1, 1, "pending", List.of()), analysis(2, 1, "pending", List.of())));
    when(eventMapper.selectList(any())).thenReturn(List.of());
    when(eventMapper.selectOne(any())).thenReturn(null);
    service.aggregate(1L);
    var events = ArgumentCaptor.forClass(OpinionEvent.class);
    verify(eventMapper, times(2)).insert(events.capture());
    assertNotEquals(events.getAllValues().get(0).getEventKey(), events.getAllValues().get(1).getEventKey());
    assertTrue(events.getAllValues().stream().allMatch(e -> e.getReportCount() == 1));
  }

  @Test
  void subjectTypeAndTimeGroupCarriesSourceSentimentTrendAndRisk() {
    when(articleMapper.selectList(any())).thenReturn(List.of(article(1), article(2)));
    when(analysisMapper.selectList(any())).thenReturn(List.of(
        analysis(1, 1, "confirmed", List.of("Company")), analysis(2, 1, "pending", List.of("Company"))));
    when(eventMapper.selectList(any())).thenReturn(List.of());
    when(eventMapper.selectOne(any())).thenReturn(null);
    service.aggregate(1L);
    var events = ArgumentCaptor.forClass(OpinionEvent.class);
    verify(eventMapper).insert(events.capture());
    var event = events.getValue();
    assertEquals(2, event.getReportCount());
    assertEquals(List.of("Company"), event.getSubjects());
    assertEquals("quality", event.getEventType());
    assertEquals("emerging", event.getTrendDirection());
    assertEquals(52, event.getRiskScore());
    assertTrue(event.getReviewRequired());
    assertFalse(event.getTimeline().isEmpty());
    assertEquals(2, event.getSentimentDist().get("negative"));
  }
}
