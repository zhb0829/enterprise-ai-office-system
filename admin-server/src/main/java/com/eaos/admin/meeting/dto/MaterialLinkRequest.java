package com.eaos.admin.meeting.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class MaterialLinkRequest {

  @NotBlank(message = "资料链接不能为空") private String url;

  private String title;
}
