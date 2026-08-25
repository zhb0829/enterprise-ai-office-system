package com.eaos.admin.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.baomidou.mybatisplus.annotation.TableField;
import com.eaos.admin.handler.PostgresJsonTypeHandler;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@Data
@TableName(value = "intelligence_report", autoResultMap = true)
public class IntelligenceReport {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String title;
    private String period;
    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> topicTags;
    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<Map<String, Object>> items;
    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private Map<String, Object> trend;
    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<Map<String, Object>> sources;
    private LocalDateTime generatedAt;
    private String model;
    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> riskFlags;
}
