package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class SuggestionFeedbackRequest {

    @NotBlank
    private String status;

    @Size(max = 2000)
    private String feedback = "";
}
