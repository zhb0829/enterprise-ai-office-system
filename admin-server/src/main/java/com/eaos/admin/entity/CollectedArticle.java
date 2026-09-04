package com.eaos.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.eaos.admin.handler.PostgresJsonTypeHandler;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

/** 情报采集文章：owner 为 Java（表结构由 V1__baseline.sql 管理），由 Python Worker 经 internal API 回写。 */
@Data
@TableName(value = "collected_article", autoResultMap = true)
public class CollectedArticle {
  @TableId(type = IdType.AUTO)
  private Long id;

  private Long sourceId;
  private String title = "";
  private String content = "";
  private String url = "";
  private String author = "";
  private LocalDateTime publishTime;
  private LocalDateTime collectedAt;
  private String contentHash = "";
  private String titleHash = "";
  private String status = "new";

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private List<Object> embedding;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private Map<String, Object> meta;
}
