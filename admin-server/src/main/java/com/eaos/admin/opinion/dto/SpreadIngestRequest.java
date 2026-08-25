package com.eaos.admin.opinion.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/** Python 传播分析结果回传（Java 权威落库）。 */
@Data
public class SpreadIngestRequest {

    @NotNull
    private Long monitorId;

    @NotNull
    @Valid
    private List<SpreadEdge> edges = new ArrayList<>();

    @Data
    public static class SpreadEdge {

        @NotNull
        private Long fromArticleId;

        @NotNull
        private Long toArticleId;

        /** 转载 / 引用 / 转发 / 回复 / 相似 */
        @NotNull
        private String relationType;

        /** 是否已验证（页面明确证据）；false 表示推测 */
        private Boolean verified = false;

        private String evidence = "";

        private BigDecimal confidence = BigDecimal.ZERO;
    }
}
