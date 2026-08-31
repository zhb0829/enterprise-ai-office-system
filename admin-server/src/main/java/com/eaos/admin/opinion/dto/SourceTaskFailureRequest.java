package com.eaos.admin.opinion.dto;

import jakarta.validation.constraints.Size;
import lombok.Data;

@Data
public class SourceTaskFailureRequest {

  @Size(max = 4000) private String error = "";
}
