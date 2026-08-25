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
@TableName(value = "opinion_article", autoResultMap = true)
public class OpinionArticle {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long sourceId;

    private Long monitorId;

    private String title;

    private String content;

    private String url;

    private String urlHash;

    private String contentHash;

    private String author;

    private LocalDateTime publishTime;

    private LocalDateTime collectedAt;

    @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
    private List<String> matchedKeywords;

    /** analysis_pending / analyzing / analyzed / analysis_failed */
    private String status;

    private String objectKey;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
