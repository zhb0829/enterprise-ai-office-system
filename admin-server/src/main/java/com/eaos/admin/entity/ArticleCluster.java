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

/** 情报聚类结果：owner 为 Java，由 Python Worker 经 internal API 全量重建。 */
@Data
@TableName(value = "article_cluster", autoResultMap = true)
public class ArticleCluster {
  @TableId(type = IdType.AUTO)
  private Long id;

  private String topic;
  private String summary = "";

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private List<Object> articleIds;

  private Integer reportCount = 0;
  private LocalDateTime timeStart;
  private LocalDateTime timeEnd;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private List<Object> sources;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private Map<String, Object> meta;

  private LocalDateTime createdAt;
  private LocalDateTime updatedAt;
}
