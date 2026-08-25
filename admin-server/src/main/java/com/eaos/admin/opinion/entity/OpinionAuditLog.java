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
@TableName(value = "opinion_audit_log", autoResultMap = true)
public class OpinionAuditLog {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String action;

    private String targetType;

    private Long targetId;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private Map<String, Object> detail;

    private String traceId;

    private LocalDateTime createdAt;
}
