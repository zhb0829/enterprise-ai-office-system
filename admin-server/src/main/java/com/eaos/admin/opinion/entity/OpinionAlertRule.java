package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.eaos.admin.handler.PostgresJsonTypeHandler;
import java.time.LocalDateTime;
import java.util.Map;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

@Data
@TableName(value = "opinion_alert_rule", autoResultMap = true)
public class OpinionAlertRule {

  @TableId(type = IdType.AUTO)
  private Long id;

  private Long monitorId;

  private String name;

  /** 关注 / 预警 / 危机 */
  private String riskLevel;

  /** {negativeCount, negativeRatio, growthRate, windowHours, sourceCount, spreadSpeed} */
  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private Map<String, Object> trigger;

  private Integer cooldownMinutes;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private Map<String, Object> escalate;

  private String status;

  private LocalDateTime createdAt;

  private LocalDateTime updatedAt;
}
