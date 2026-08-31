package com.eaos.admin.meeting.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class TranscriptRequest {

  private String title;

  @NotBlank(message = "转录文本不能为空") private String content;
}
