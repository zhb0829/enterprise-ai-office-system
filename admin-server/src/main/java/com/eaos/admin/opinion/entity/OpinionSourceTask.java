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
@TableName(value = "opinion_source_task", autoResultMap = true)
public class OpinionSourceTask {

  @TableId(type = IdType.AUTO)
  private Long id;

  private Long sourceId;

  private Long monitorId;

  private String taskType;

  private String status;

  private LocalDateTime startedAt;

  private LocalDateTime finishedAt;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private Map<String, Object> payload;

  private Integer itemsSent;

  private Integer itemsIngested;

  private Integer retryCount;

  private String worker;

  private String error;

  private LocalDateTime createdAt;

  private LocalDateTime updatedAt;
}
