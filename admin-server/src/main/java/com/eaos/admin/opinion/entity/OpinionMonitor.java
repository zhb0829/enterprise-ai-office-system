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
@TableName(value = "opinion_monitor", autoResultMap = true)
public class OpinionMonitor {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String name;

    private String enterpriseName;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> brandWords;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> competitorWords;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> executiveNames;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> excludeWords;

    /** any / all：任一命中或全部命中才判定相关 */
    private String matchMode;

    private Integer timeWindowDays;

    private String status;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
