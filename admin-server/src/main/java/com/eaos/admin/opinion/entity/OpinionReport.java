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
import java.util.Map;

@Data
@TableName(value = "opinion_report", autoResultMap = true)
public class OpinionReport {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long monitorId;

    /** daily / weekly / manual */
    private String period;

    private LocalDateTime periodStart;

    private LocalDateTime periodEnd;

    private String title;

    private String summary;

    private String contentHtml;

    /** draft / published */
    private String status;

    private Integer version;

    private String model;

    private String promptVersion;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private Map<String, Object> dataScope;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<Object> evidence;

    private String publishedBy;

    private LocalDateTime publishedAt;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
