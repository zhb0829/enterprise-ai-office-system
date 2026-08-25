package com.eaos.admin.opinion.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.eaos.admin.opinion.dto.AlertRuleRequest;
import com.eaos.admin.opinion.entity.OpinionAlertRule;
import com.eaos.admin.opinion.mapper.OpinionAlertRuleMapper;
import com.eaos.admin.opinion.support.OpinionAuditService;
import com.eaos.admin.opinion.support.OpinionCurrentUser;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Service
@RequiredArgsConstructor
public class OpinionAlertRuleService {

    private final OpinionAlertRuleMapper ruleMapper;
    private final OpinionAuditService auditService;

    public List<OpinionAlertRule> list(Long monitorId) {
        var wrapper = Wrappers.<OpinionAlertRule>lambdaQuery();
        if (monitorId != null) {
            wrapper.eq(OpinionAlertRule::getMonitorId, monitorId);
        }
        return ruleMapper.selectList(wrapper.orderByDesc(OpinionAlertRule::getCreatedAt));
    }

    public OpinionAlertRule create(AlertRuleRequest request) {
        OpinionAlertRule rule = new OpinionAlertRule();
        apply(rule, request);
        ruleMapper.insert(rule);
        auditService.record("ALERT_RULE_CREATE", "opinion_alert_rule", rule.getId(),
                Map.of("name", rule.getName(), "monitorId", rule.getMonitorId()), null);
        return rule;
    }

    public OpinionAlertRule update(Long id, AlertRuleRequest request) {
        OpinionAlertRule rule = ruleMapper.selectById(id);
        if (rule == null) {
            throw new IllegalArgumentException("告警规则不存在");
        }
        apply(rule, request);
        rule.setUpdatedAt(LocalDateTime.now());
        ruleMapper.updateById(rule);
        auditService.record("ALERT_RULE_UPDATE", "opinion_alert_rule", id,
                Map.of("name", rule.getName()), null);
        return rule;
    }

    public void delete(Long id) {
        if (ruleMapper.deleteById(id) == 0) {
            throw new IllegalArgumentException("告警规则不存在");
        }
        auditService.record("ALERT_RULE_DELETE", "opinion_alert_rule", id, Map.of(), null);
    }

    public OpinionAlertRule toggle(Long id) {
        OpinionAlertRule rule = ruleMapper.selectById(id);
        if (rule == null) {
            throw new IllegalArgumentException("告警规则不存在");
        }
        rule.setStatus("enabled".equalsIgnoreCase(rule.getStatus()) ? "disabled" : "enabled");
        rule.setUpdatedAt(LocalDateTime.now());
        ruleMapper.updateById(rule);
        return rule;
    }

    private void apply(OpinionAlertRule rule, AlertRuleRequest request) {
        rule.setMonitorId(request.getMonitorId());
        rule.setName(request.getName().trim());
        rule.setRiskLevel(request.getRiskLevel());
        rule.setTrigger(request.getTrigger() == null ? Map.of() : request.getTrigger());
        rule.setCooldownMinutes(request.getCooldownMinutes() == null ? 60 : request.getCooldownMinutes());
        rule.setEscalate(request.getEscalate() == null ? Map.of() : request.getEscalate());
        rule.setStatus(request.getStatus() == null ? "enabled" : request.getStatus());
    }
}
