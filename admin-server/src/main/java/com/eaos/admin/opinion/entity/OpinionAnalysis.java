package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.eaos.admin.handler.PostgresJsonTypeHandler;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

@Data
@TableName(value = "opinion_analysis", autoResultMap = true)
public class OpinionAnalysis {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long articleId;

    private Long monitorId;

    /** positive / neutral / negative */
    private String sentiment;

    private BigDecimal confidence;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> emotionTags;

    private String reason;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> evidenceIds;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> riskFactors;

    private Integer riskScore;

    private String topic;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> keywords;

    private String model;

    private String promptVersion;

    private String aiRunId;

    /** pending / confirmed / rejected */
    private String status;

    private Integer version;

    /** ai / manual */
    private String source;

    private String auditedBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
