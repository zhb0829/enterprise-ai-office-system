package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.ArrayList;
import java.util.List;
import lombok.Data;

@Data
public class OpinionMonitorRequest {

  @NotBlank @Size(max = 128) private String name;

  @Size(max = 128) private String enterpriseName;

  private List<String> brandWords = new ArrayList<>();

  private List<String> competitorWords = new ArrayList<>();

  private List<String> executiveNames = new ArrayList<>();

  private List<String> excludeWords = new ArrayList<>();

  /** any：任一命中即相关（默认）；all：全部命中才相关 */
  private String matchMode = "any";

  private Integer timeWindowDays = 7;

  private String status = "enabled";
}
