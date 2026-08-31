package com.eaos.admin.meeting.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("conference")
public class Conference {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String name;

    private String category;

    private LocalDateTime startTime;

    private LocalDateTime endTime;

    private String location;

    private String organizer;

    private String description;

    /** 采集过滤关键词，逗号分隔 */
    private String keywords;

    /** 竞品名单，逗号分隔 */
    private String competitors;

    /** draft / processing / completed */
    private String status;

    private Boolean archived;

    private String lastError;

    private String createdBy;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
