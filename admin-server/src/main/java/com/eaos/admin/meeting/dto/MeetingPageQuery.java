package com.eaos.admin.meeting.dto;

import lombok.Data;

@Data
public class MeetingPageQuery {

  private Integer page = 1;

  private Integer pageSize = 20;

  /** draft / processing / completed */
  private String status;

  private String keyword;

  private Boolean archived;
}
