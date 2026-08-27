package com.eaos.admin.qual_doc;

import jakarta.validation.constraints.NotBlank;

import java.util.List;
import java.util.Map;

public final class QualDto {
    private QualDto() {
    }

    public record CreateTaskRequest(
            @NotBlank String qualificationType,
            @NotBlank String guideSchemaId,
            @NotBlank String documentType,
            List<String> materialIds,
            Map<String, Object> formatRequirements,
            String idempotencyKey
    ) {
    }

    public record SaveDocumentRequest(Map<String, Object> content, String changeNote) {
    }

    public record ReviewRequest(String comment) {
    }

    public record CreateRuleRequest(
            @NotBlank String code,
            @NotBlank String name,
            @NotBlank String ruleType,
            Map<String, Object> rule,
            Boolean enabled
    ) {
    }

    public record InternalProgress(
            @NotBlank String protocolVersion,
            @NotBlank String taskId,
            @NotBlank String idempotencyKey,
            @NotBlank String phase,
            Integer progress,
            String message,
            Integer chapterIndex,
            Integer chapterTotal
    ) {
    }

    public record InternalResult(
            @NotBlank String protocolVersion,
            @NotBlank String taskId,
            @NotBlank String idempotencyKey,
            @NotBlank String status,
            Map<String, Object> document,
            List<Map<String, Object>> sources,
            List<String> riskFlags,
            String generatedAt,
            String model
    ) {
    }

    public record InternalFailure(
            @NotBlank String protocolVersion,
            @NotBlank String taskId,
            @NotBlank String idempotencyKey,
            @NotBlank String message
    ) {
    }
}
