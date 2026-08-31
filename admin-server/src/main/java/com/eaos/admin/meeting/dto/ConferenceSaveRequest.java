package com.eaos.admin.meeting.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import jakarta.validation.constraints.NotBlank;
import java.time.LocalDateTime;
import lombok.Data;

@Data
public class ConferenceSaveRequest {

  @NotBlank(message = "会议名称不能为空") private String name;

  private String category;

  @JsonFormat(pattern = "yyyy-MM-dd HH:mm")
  private LocalDateTime startTime;

  @JsonFormat(pattern = "yyyy-MM-dd HH:mm")
  private LocalDateTime endTime;

  private String location;

  private String organizer;

  private String description;

  /** 采集过滤关键词，逗号分隔 */
  private String keywords;

  /** 竞品名单，逗号分隔 */
  private String competitors;
}
