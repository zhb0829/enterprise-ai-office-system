package com.eaos.admin.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import java.util.ArrayList;
import java.util.List;
import lombok.Data;

@Data
public class SourceConfigRequest {
  @NotBlank(message = "来源名称不能为空") private String name;

  @NotBlank(message = "来源类型不能为空") @Pattern(regexp = "web|rss|api", message = "来源类型必须是 web/rss/api") private String type;

  @NotBlank(message = "来源 URL 不能为空") private String url;

  private List<String> keywords = new ArrayList<>();
  private List<String> competitors = new ArrayList<>();
  private String frequency = "daily";
  private String status = "enabled";
}
