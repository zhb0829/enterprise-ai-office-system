package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Data;

@Data
@TableName("opinion_notification")
public class OpinionNotification {

  @TableId(type = IdType.AUTO)
  private Long id;

  private Long alertId;

  private String channel;

  private String target;

  private String content;

  private String status;

  private Integer retryCount;

  private LocalDateTime nextRetryAt;

  private String error;

  private LocalDateTime sentAt;

  private LocalDateTime createdAt;
}
