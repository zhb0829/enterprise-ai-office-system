package com.eaos.admin.opinion.dto;

import lombok.Data;

/** 舆情文章/事件分页查询参数 */
@Data
public class OpinionPageQuery {

  private Long userId;

  private Long monitorId;

  private Long sourceId;

  private String sentiment;

  private String keyword;

  private Integer page = 1;

  private Integer pageSize = 20;
}
