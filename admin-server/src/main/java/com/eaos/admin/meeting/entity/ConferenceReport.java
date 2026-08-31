package com.eaos.admin.meeting.entity;

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
@TableName(value = "conference_report", autoResultMap = true)
public class ConferenceReport {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long conferenceId;

    private Integer version;

    /** Markdown 正文 */
    private String content;

    private String triggerReason;

    private String generatedByModel;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<Map<String, Object>> relatedPolicies;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<Map<String, Object>> relatedConferences;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<Map<String, Object>> relatedCompetitors;

    private LocalDateTime createdAt;
}
