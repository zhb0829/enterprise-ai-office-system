package com.eaos.admin.meeting.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

import java.util.List;
import java.util.Map;

/** Python 整理任务结果回调载荷 */
@Data
public class MeetingResultPayload {

    private String model;

    private ReportPayload report;

    private List<Map<String, Object>> cards;

    private List<Map<String, Object>> media;

    private List<Map<String, Object>> materials;

    private List<Map<String, Object>> steps;

    @Data
    public static class ReportPayload {
        private String content;
        private List<Map<String, Object>> relatedPolicies;
        private List<Map<String, Object>> relatedConferences;
        private List<Map<String, Object>> relatedCompetitors;
    }
}
