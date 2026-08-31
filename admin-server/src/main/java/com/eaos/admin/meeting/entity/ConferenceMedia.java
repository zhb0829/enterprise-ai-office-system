package com.eaos.admin.meeting.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("conference_media")
public class ConferenceMedia {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long conferenceId;

    private String title;

    private String sourceUrl;

    private String sourceName;

    private LocalDateTime publishedAt;

    private String summary;

    private String contentPath;

    private LocalDateTime collectedAt;
}
