package com.eaos.admin.qual_doc;

import com.eaos.admin.config.AiServiceProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/internal/qual")
@RequiredArgsConstructor
public class QualInternalController {

  private final QualDocService service;
  private final AiServiceProperties properties;

  @PostMapping("/progress")
  public void progress(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestBody QualDto.InternalProgress request) {
    verify(token);
    service.internalProgress(request);
  }

  @PostMapping("/result")
  public void result(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestBody QualDto.InternalResult request) {
    verify(token);
    service.internalResult(request);
  }

  @PostMapping("/failure")
  public void failure(
      @RequestHeader(value = "X-Internal-Token", required = false) String token,
      @RequestBody QualDto.InternalFailure request) {
    verify(token);
    service.internalFailure(request);
  }

  private void verify(String token) {
    if (properties.getInternalToken() == null
        || properties.getInternalToken().isBlank()
        || !properties.getInternalToken().equals(token)) {
      throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "invalid internal token");
    }
  }
}
