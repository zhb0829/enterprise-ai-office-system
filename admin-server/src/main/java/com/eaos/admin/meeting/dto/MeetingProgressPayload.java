package com.eaos.admin.meeting.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.List;
import java.util.Map;

/** Python 整理任务进度回调载荷 */
@Data
public class MeetingProgressPayload {

    @NotNull(message = "任务步骤状态不能为空")
    private List<Map<String, Object>> steps;

    /** running / partial */
    @NotBlank(message = "任务状态不能为空")
    private String status;

    /** 已完成解析的资料快照，用于失败后的断点重试。 */
    private List<Map<String, Object>> materials;
}
