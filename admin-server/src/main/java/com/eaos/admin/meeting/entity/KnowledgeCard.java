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
@TableName(value = "knowledge_card", autoResultMap = true)
public class KnowledgeCard {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long conferenceId;

    private Long reportId;

    /** 核心观点 / 决策事项 / 行动项 / 专家观点 / 关键数据 */
    private String cardType;

    private String title;

    private String content;

    /** 行动项的行为主体（如“工信部”“某厂商”），可选 */
    private String actor;

    private String expectedTime;

    /** 来源引用：[{materialId, location, quote}]，必填 */
    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<Map<String, Object>> sourceRef;

    private LocalDateTime createdAt;
}
