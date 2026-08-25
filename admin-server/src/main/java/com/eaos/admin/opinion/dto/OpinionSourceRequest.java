package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.time.LocalDateTime;

@Data
public class OpinionSourceRequest {

    @NotBlank
    @Size(max = 128)
    private String name;

    @NotBlank
    @Size(max = 16)
    private String sourceType;

    @Size(max = 64)
    private String platform = "";

    @NotBlank
    @Size(max = 2048)
    private String homepage;

    @Size(max = 128)
    private String authSubject = "";

    @Size(max = 256)
    private String authScope = "";

    private LocalDateTime authStart;

    private LocalDateTime authExpire;

    @Size(max = 32)
    private String collectMethod = "http";

    @Size(max = 32)
    private String frequency = "daily";

    @Size(max = 128)
    private String rateLimit = "";

    private Integer priority = 0;

    @Size(max = 64)
    private String adapterVersion = "v1";

    private String status = "disabled";
}
