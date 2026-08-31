package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.LocalDateTime;
import lombok.Data;

@Data
@TableName("opinion_source")
public class OpinionSource {

  @TableId(type = IdType.AUTO)
  private Long id;

  private String name;

  private String sourceType;

  private String platform;

  private String homepage;

  private String authSubject;

  private String authScope;

  private LocalDateTime authStart;

  private LocalDateTime authExpire;

  private String collectMethod;

  private String frequency;

  private String rateLimit;

  private Integer priority;

  private String adapterVersion;

  private String status;

  private String healthStatus;

  private Integer failureCount;

  private LocalDateTime lastCollectAt;

  private LocalDateTime lastSuccessAt;

  private String lastError;

  private String auditStatus;

  private String auditBy;

  private LocalDateTime auditAt;

  private String auditNote;

  private String createdBy;

  private LocalDateTime createdAt;

  private LocalDateTime updatedAt;
}
