package com.eaos.admin.opinion.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.ArrayList;
import java.util.List;

@Data
public class IngestArticlesRequest {

    /** 采集任务 ID（来自 opinion_source_task），用于幂等与审计 */
    private Long sourceTaskId;

    @NotNull
    private Long sourceId;

    private Long monitorId;

    @NotNull
    @Valid
    private List<IngestArticleItem> items = new ArrayList<>();

    @Data
    public static class IngestArticleItem {

        private String title = "";

        private String content = "";

        private String url = "";

        private String author = "";

        private String publishTime;

        private String contentHash;

        private String urlHash;
    }
}
