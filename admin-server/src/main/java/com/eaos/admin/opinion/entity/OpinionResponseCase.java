package com.eaos.admin.opinion.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.eaos.admin.handler.PostgresJsonTypeHandler;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

import java.time.LocalDateTime;
import java.util.List;

@Data
@TableName(value = "opinion_response_case", autoResultMap = true)
public class OpinionResponseCase {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String title;

    private String eventType;

    private String riskLevel;

    private String strategy;

    private String content;

    private String effect;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> tags;

    private String source;

    private String createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
