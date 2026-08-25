package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.eaos.admin.handler.PostgresJsonTypeHandler;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

import java.time.LocalDateTime;
import java.util.Map;

@Data
@TableName(value = "opinion_review", autoResultMap = true)
public class OpinionReview {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String targetType;

    private Long targetId;

    private String field;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private Map<String, Object> oldValue;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private Map<String, Object> newValue;

    private String reason;

    private String reviewedBy;

    private LocalDateTime reviewedAt;
}
