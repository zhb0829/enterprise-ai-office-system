package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.eaos.admin.handler.PostgresJsonTypeHandler;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

@Data
@TableName(value = "opinion_event", autoResultMap = true)
public class OpinionEvent {

  @TableId(type = IdType.AUTO)
  private Long id;

  private Long monitorId;

  private String title;

  private String summary;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private List<Long> articleIds;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private Map<String, Object> sentimentDist;

  /** 关注 / 预警 / 危机 */
  private String riskLevel;

  private LocalDateTime timeStart;

  private LocalDateTime timeEnd;

  private BigDecimal sourceWeight;

  private Integer spreadSpeed;

  private Integer reportCount;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private List<String> keywords;

  private String status;

  private Integer version;

  private LocalDateTime createdAt;

  private LocalDateTime updatedAt;
}
