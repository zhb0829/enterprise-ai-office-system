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
@TableName(value = "opinion_alert_event", autoResultMap = true)
public class OpinionAlertEvent {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long monitorId;

    private Long ruleId;

    private Long eventId;

    /** 关注 / 预警 / 危机 */
    private String riskLevel;

    /** triggered / acknowledged / processing / resolved / closed */
    private String state;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private Map<String, Object> triggerStats;

    private Integer triggerCount;

    private LocalDateTime firstTriggeredAt;

    private LocalDateTime lastTriggeredAt;

    private LocalDateTime resolvedAt;

    private String owner;

    private String handleNote;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
