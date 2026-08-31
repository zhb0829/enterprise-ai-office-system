package com.eaos.admin.entity;

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
@TableName(value = "source_config", autoResultMap = true)
public class SourceConfig {
  @TableId(type = IdType.AUTO)
  private Long id;

  private String name;
  private String type;
  private String url;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private List<String> keywords;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private List<String> competitors;

  private String frequency;
  private String status;
  private String healthStatus;
  private Integer consecutiveFailures = 0;
  private LocalDateTime lastRunAt;
  private LocalDateTime lastSuccessAt;
  private String lastError = "";
  private LocalDateTime createdAt;
  private LocalDateTime updatedAt;
}
