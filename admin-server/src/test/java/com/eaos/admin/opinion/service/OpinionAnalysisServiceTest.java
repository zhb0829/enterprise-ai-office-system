package com.eaos.admin.opinion.service;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import com.eaos.admin.opinion.config.OpinionServiceProperties;
import com.eaos.admin.opinion.dto.ReviewRequest;
import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionReview;
import com.eaos.admin.opinion.mapper.*;
import com.eaos.admin.opinion.support.*;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class OpinionAnalysisServiceTest {
  @Mock OpinionAnalysisTaskMapper taskMapper;
  @Mock OpinionAnalysisMapper analysisMapper;
  @Mock OpinionArticleMapper articleMapper;
  @Mock OpinionReviewMapper reviewMapper;
  @Mock OpinionAuditService auditService;
  @Mock OpinionEventService eventService;
  @Mock OpinionAlertEngine alertEngine;
  @Mock OpinionServiceProperties properties;
  @Mock OpinionAccessService accessService;
  @InjectMocks OpinionAnalysisService service;

  @Test
  void reviewCreatesImmutableVersionUnderArticleLockAndRecalculatesEvents() {
    var original = new OpinionAnalysis();
    original.setId(7L);
    original.setArticleId(11L);
    original.setMonitorId(1L);
    original.setVersion(1);
    original.setSource("ai");
    original.setStatus("pending");
    original.setSentiment("negative");
    original.setConfidence(BigDecimal.ONE);
    original.setSubjects(List.of("Company"));
    original.setEventType("quality");
    when(analysisMapper.selectById(7L)).thenReturn(original);
    when(analysisMapper.selectOne(any())).thenReturn(original);
    doAnswer(call -> {
      ((OpinionAnalysis) call.getArgument(0)).setId(8L);
      return 1;
    }).when(analysisMapper).insert(any(OpinionAnalysis.class));
    var request = new ReviewRequest();
    request.setStatus("rejected");
    request.setField("status");
    var result = service.review(7L, request);
    assertEquals(2, result.getVersion());
    assertEquals("manual", result.getSource());
    assertEquals("rejected", result.getStatus());
    assertEquals("pending", original.getStatus());
    assertEquals(1, original.getVersion());
    assertEquals(List.of("Company"), result.getSubjects());
    var order = inOrder(articleMapper, analysisMapper, eventService, alertEngine);
    order.verify(articleMapper).lockArticle(11L);
    order.verify(analysisMapper).selectOne(any());
    order.verify(analysisMapper).insert(result);
    order.verify(eventService).aggregate(1L);
    order.verify(alertEngine).evaluate(1L);
    var review = ArgumentCaptor.forClass(OpinionReview.class);
    verify(reviewMapper).insert(review.capture());
    assertEquals(8L, review.getValue().getTargetId());
  }
}
