package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class AlertHandleRequest {

    /** acknowledged / processing / resolved / closed */
    @NotBlank
    private String state;

    @Size(max = 2000)
    private String note = "";

    @Size(max = 64)
    private String owner = "";
}
