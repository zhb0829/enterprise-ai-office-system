package com.eaos.admin.service.impl;

import com.eaos.admin.config.AiServiceProperties;
import com.eaos.admin.service.AiService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

@Slf4j
@Service
@RequiredArgsConstructor
public class AiServiceImpl implements AiService {

    private final RestTemplate restTemplate;
    private final AiServiceProperties aiServiceProperties;

    @Override
    public String health() {
        String url = aiServiceProperties.getBaseUrl()
                + aiServiceProperties.getInternalPrefix() + "/health";
        log.info("调用 Python agent 服务: {}", url);
        try {
            return restTemplate.getForObject(url, String.class);
        } catch (Exception e) {
            log.warn("Python agent 服务不可用: {}", e.getMessage());
            return "AI service unavailable: " + e.getMessage();
        }
    }
}