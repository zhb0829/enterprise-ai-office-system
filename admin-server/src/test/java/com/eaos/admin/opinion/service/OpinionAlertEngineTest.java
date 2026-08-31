package com.eaos.admin.opinion.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.eaos.admin.opinion.entity.OpinionAlertEvent;
import com.eaos.admin.opinion.entity.OpinionAlertRule;
import com.eaos.admin.opinion.entity.OpinionAnalysis;
import com.eaos.admin.opinion.entity.OpinionArticle;
import com.eaos.admin.opinion.mapper.OpinionAlertEventMapper;
import com.eaos.admin.opinion.mapper.OpinionAlertRuleMapper;
import com.eaos.admin.opinion.mapper.OpinionAnalysisMapper;
import com.eaos.admin.opinion.mapper.OpinionArticleMapper;
import com.eaos.admin.opinion.mapper.OpinionEventMapper;
import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class OpinionAlertEngineTest {

  @Mock private OpinionAlertRuleMapper ruleMapper;
  @Mock private OpinionAlertEventMapper eventMapper;
  @Mock private OpinionArticleMapper articleMapper;
  @Mock private OpinionAnalysisMapper analysisMapper;
  @Mock private OpinionEventMapper eventMapper2;
  @Mock private OpinionNotificationService notificationService;

  @InjectMocks private OpinionAlertEngine engine;

  private OpinionAlertRule ruleWithTrigger() {
    OpinionAlertRule rule = new OpinionAlertRule();
    rule.setId(11L);
    rule.setMonitorId(1L);
    rule.setStatus("enabled");
    rule.setRiskLevel("关注");
    rule.setCooldownMinutes(60);
    Map<String, Object> trigger = new HashMap<>();
    trigger.put("negativeCount", 1);
    rule.setTrigger(trigger);
    return rule;
  }

  private void stubStatsTwoArticlesOneNegative() {
    OpinionArticle a1 = new OpinionArticle();
    a1.setId(101L);
    a1.setMonitorId(1L);
    a1.setSourceId(5L);
    OpinionArticle a2 = new OpinionArticle();
    a2.setId(102L);
    a2.setMonitorId(1L);
    a2.setSourceId(6L);
    when(articleMapper.selectList(any())).thenReturn(List.of(a1, a2));

    OpinionAnalysis negative = new OpinionAnalysis();
    negative.setArticleId(101L);
    negative.setSentiment("negative");
    OpinionAnalysis positive = new OpinionAnalysis();
    positive.setArticleId(102L);
    positive.setSentiment("positive");
    when(analysisMapper.selectList(any())).thenReturn(List.of(negative, positive));
    when(eventMapper2.selectList(any())).thenReturn(List.of());
  }

  @Test
  void firstHitInsertsNewAlertAndNotifies() {
    when(ruleMapper.selectList(any())).thenReturn(List.of(ruleWithTrigger()));
    stubStatsTwoArticlesOneNegative();
    when(eventMapper.selectOne(any())).thenReturn(null);

    engine.evaluate(1L);

    ArgumentCaptor<OpinionAlertEvent> captor = ArgumentCaptor.forClass(OpinionAlertEvent.class);
    verify(eventMapper).insert(captor.capture());
    assertEquals("triggered", captor.getValue().getState());
    assertEquals(1, captor.getValue().getTriggerCount());
    verify(notificationService).notifyAlert(any(), any(), any());
  }

  @Test
  void hitWithinCooldownMergesIntoExistingAlertWithoutNotify() {
    when(ruleMapper.selectList(any())).thenReturn(List.of(ruleWithTrigger()));
    stubStatsTwoArticlesOneNegative();
    OpinionAlertEvent existing = new OpinionAlertEvent();
    existing.setId(99L);
    existing.setMonitorId(1L);
    existing.setRuleId(11L);
    existing.setRiskLevel("关注");
    existing.setState("resolved");
    existing.setTriggerCount(1);
    existing.setLastTriggeredAt(LocalDateTime.now().minusMinutes(10));
    when(eventMapper.selectOne(any())).thenReturn(existing);

    engine.evaluate(1L);

    verify(eventMapper, never()).insert(any(OpinionAlertEvent.class));
    verify(eventMapper).updateById(existing);
    assertEquals(2, existing.getTriggerCount());
    // 冷却期内合并：resolved 重新置为 triggered，且不重复发送通知
    assertEquals("triggered", existing.getState());
    verify(notificationService, never()).notifyAlert(any(), any(), any());
  }

  @Test
  void escalateConfigRaisesLevel() {
    OpinionAlertRule rule = ruleWithTrigger();
    Map<String, Object> escalate = new HashMap<>();
    escalate.put("crisisCount", 100);
    escalate.put("warningCount", 1);
    rule.setEscalate(escalate);
    when(ruleMapper.selectList(any())).thenReturn(List.of(rule));
    stubStatsTwoArticlesOneNegative();
    when(eventMapper.selectOne(any())).thenReturn(null);

    engine.evaluate(1L);

    ArgumentCaptor<OpinionAlertEvent> captor = ArgumentCaptor.forClass(OpinionAlertEvent.class);
    verify(eventMapper).insert(captor.capture());
    assertEquals("预警", captor.getValue().getRiskLevel());
  }

  @Test
  void statsBelowTriggerDoNothing() {
    when(ruleMapper.selectList(any())).thenReturn(List.of(ruleWithTrigger()));
    // 无文章 → 全部统计为 0，不满足 negativeCount>=1
    when(articleMapper.selectList(any())).thenReturn(List.of());

    engine.evaluate(1L);

    verify(eventMapper, never()).insert(any(OpinionAlertEvent.class));
    verify(eventMapper, never()).updateById(any(OpinionAlertEvent.class));
    verify(notificationService, never()).notifyAlert(any(), any(), any());
  }
}
