package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.eaos.admin.handler.PostgresJsonTypeHandler;
import java.time.LocalDateTime;
import java.util.List;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

@Data
@TableName(value = "opinion_suggestion", autoResultMap = true)
public class OpinionSuggestion {

  @TableId(type = IdType.AUTO)
  private Long id;

  /** alert / event */
  private String targetType;

  private Long targetId;

  private Long monitorId;

  private String content;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private List<Object> citations;

  private String model;

  private String promptVersion;

  private String status;

  private String feedback;

  private String createdBy;

  private LocalDateTime createdAt;
}
