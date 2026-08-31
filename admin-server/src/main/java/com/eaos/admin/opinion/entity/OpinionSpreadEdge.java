package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import lombok.Data;

@Data
@TableName("opinion_spread_edge")
public class OpinionSpreadEdge {

  @TableId(type = IdType.AUTO)
  private Long id;

  private Long monitorId;

  private Long fromArticleId;

  private Long toArticleId;

  /** 转载 / 引用 / 转发 / 回复 / 相似 */
  private String relationType;

  private Boolean verified;

  private String evidence;

  private BigDecimal confidence;

  private LocalDateTime createdAt;
}
