package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.Pattern;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import lombok.Data;

@Data
public class ReviewRequest {

  @NotBlank private String targetType;

  @NotNull private Long targetId;

  /** 修正字段：sentiment / risk_level / risk_score / status 等 */
  @NotBlank private String field;

  @Pattern(regexp = "positive|neutral|negative")
  private String sentiment;

  @DecimalMin("0") @DecimalMax("1")
  private BigDecimal confidence;

  private List<String> emotionTags = new ArrayList<>();

  @Min(0) @Max(100)
  private Integer riskScore;

  private String topic;

  @Pattern(regexp = "pending|confirmed|rejected")
  private String status;

  @Size(max = 2000) private String reason = "";
}
