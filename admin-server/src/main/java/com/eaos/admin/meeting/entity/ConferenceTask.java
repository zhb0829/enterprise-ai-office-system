package com.eaos.admin.meeting.entity;

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

@Data
@TableName(value = "conference_task", autoResultMap = true)
public class ConferenceTask {

  @TableId(type = IdType.AUTO)
  private Long id;

  private Long conferenceId;

  /** reorganize / collect */
  private String taskType;

  /** pending / running / succeeded / failed / partial */
  private String status;

  /** 各步骤状态：[{step, status, elapsedMs, error}] */
  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private List<Map<String, Object>> progress;

  private String error;

  private Integer retryCount;

  private LocalDateTime startedAt;

  private LocalDateTime finishedAt;

  private LocalDateTime createdAt;
}
