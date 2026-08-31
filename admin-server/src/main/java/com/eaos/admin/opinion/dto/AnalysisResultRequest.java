package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotNull;
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
  @NotNull private String sentiment;

  private BigDecimal confidence = BigDecimal.ZERO;

  private List<String> emotionTags = new ArrayList<>();

  private String reason = "";

  private List<String> evidenceIds = new ArrayList<>();

  private List<String> riskFactors = new ArrayList<>();

  private Integer riskScore = 0;

  private String topic = "";

  private List<String> keywords = new ArrayList<>();

  private String model = "";

  private String promptVersion = "";

  private String aiRunId = "";
}
