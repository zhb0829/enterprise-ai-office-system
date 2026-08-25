package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class ResponseCaseRequest {

    @NotBlank
    @Size(max = 256)
    private String title;

    @Size(max = 128)
    private String eventType = "";

    private String riskLevel = "关注";

    private String strategy = "";

    private String content = "";

    private String effect = "";

    private List<String> tags = new ArrayList<>();

    @Size(max = 64)
    private String source = "";
}
