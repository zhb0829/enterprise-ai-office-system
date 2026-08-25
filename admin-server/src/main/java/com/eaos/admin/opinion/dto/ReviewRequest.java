package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

@Data
public class ReviewRequest {

    @NotBlank
    private String targetType;

    @NotNull
    private Long targetId;

    /** 修正字段：sentiment / risk_level / risk_score / status 等 */
    @NotBlank
    private String field;

    private String sentiment;

    private BigDecimal confidence;

    private List<String> emotionTags = new ArrayList<>();

    private Integer riskScore;

    private String topic;

    private String status;

    @Size(max = 2000)
    private String reason = "";
}
