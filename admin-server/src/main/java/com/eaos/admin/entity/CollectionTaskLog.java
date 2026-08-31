package com.eaos.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Data;

@Data
@TableName("collection_task_log")
public class CollectionTaskLog {
  @TableId(type = IdType.AUTO)
  private Long id;

  private Long sourceId;
  private String celeryTaskId;
  private LocalDateTime startedAt;
  private LocalDateTime finishedAt;
  private String status;
  private String error;
  private Integer itemsCount;
  private Integer retryCount;
  private LocalDateTime createdAt;
}
