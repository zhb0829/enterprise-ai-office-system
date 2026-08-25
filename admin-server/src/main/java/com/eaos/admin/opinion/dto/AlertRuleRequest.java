package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.Map;

@Data
public class AlertRuleRequest {

    @NotNull
    private Long monitorId;

    @NotBlank
    @Size(max = 128)
    private String name;

    @NotBlank
    private String riskLevel;

    /** 触发条件：{negativeCount, negativeRatio, growthRate, windowHours, sourceCount, spreadSpeed} */
    private Map<String, Object> trigger;

    private Integer cooldownMinutes = 60;

    private Map<String, Object> escalate;

    private String status = "enabled";
}
