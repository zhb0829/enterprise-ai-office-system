package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class SourceAuditRequest {

    @NotBlank
    private String auditStatus;

    @Size(max = 2000)
    private String auditNote = "";
}
