package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import lombok.Data;

@Data
public class AnalysisResultRequest {

  @NotNull private Long taskId;

  @NotNull private Long articleId;

  private Long monitorId;

  /** positive / neutral / negative */
  @NotNull @Pattern(regexp = "positive|neutral|negative") private String sentiment;

  @DecimalMin("0") @DecimalMax("1")
  private BigDecimal confidence = BigDecimal.ZERO;

  private List<String> emotionTags = new ArrayList<>();

  private String reason = "";

  private List<String> evidenceIds = new ArrayList<>();

  private List<String> riskFactors = new ArrayList<>();

  @Min(0) @Max(100)
  private Integer riskScore = 0;

  private String topic = "";

  @Size(max = 20)
  private List<@Size(max = 128) String> subjects = new ArrayList<>();

  @Pattern(regexp = "quality|safety|compliance|business|privacy|service|other")
  private String eventType = "other";

  @Size(max = 64)
  private String riskModelVersion = "opinion-risk-v1";

  private List<String> keywords = new ArrayList<>();

  private String model = "";

  private String promptVersion = "";

  private String aiRunId = "";
}
