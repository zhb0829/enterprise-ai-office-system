package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("opinion_analysis_task")
public class OpinionAnalysisTask {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long articleId;

    private Long monitorId;

    /** queued / claimed / analyzing / success / failed */
    private String status;

    private Integer retryCount;

    private LocalDateTime nextRetryAt;

    private String worker;

    private LocalDateTime claimedAt;

    private String lastError;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
