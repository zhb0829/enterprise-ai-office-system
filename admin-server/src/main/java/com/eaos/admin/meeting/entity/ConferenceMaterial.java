package com.eaos.admin.meeting.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.eaos.admin.handler.PostgresJsonTypeHandler;
import java.time.LocalDateTime;
import java.util.Map;
import lombok.Data;
import org.apache.ibatis.type.JdbcType;

@Data
@TableName(value = "conference_material", autoResultMap = true)
public class ConferenceMaterial {

  @TableId(type = IdType.AUTO)
  private Long id;

  private Long conferenceId;

  /** link / file / transcript / image / audio */
  private String materialType;

  private String title;

  private String sourceUrl;

  private String filePath;

  private String fileSha256;

  private String mimeType;

  private Long sizeBytes;

  /** pending / parsed / failed */
  private String parseStatus;

  @TableField(jdbcType = JdbcType.OTHER, typeHandler = PostgresJsonTypeHandler.class)
  private Map<String, Object> parseResult;

  private LocalDateTime createdAt;
}
