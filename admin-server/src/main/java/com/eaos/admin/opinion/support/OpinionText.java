package com.eaos.admin.opinion.support;

import com.eaos.admin.opinion.entity.OpinionMonitor;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/** 纯文本工具：监控词匹配与去重哈希。无 Spring 依赖，便于单元测试。 */
public final class OpinionText {

    private OpinionText() {
    }

    /** 匹配监控词：排除词优先否决；any 命中任一，all 需全部命中。 */
    public static List<String> matchKeywords(OpinionMonitor monitor, String title, String content) {
        String text = normalize(title + " " + content);
        Set<String> matched = new LinkedHashSet<>();
        for (String exclude : orEmpty(monitor.getExcludeWords())) {
            if (exclude != null && !exclude.isBlank() && text.contains(normalize(exclude))) {
                return List.of();
            }
        }
        List<String> positives = new ArrayList<>();
        positives.addAll(orEmpty(monitor.getBrandWords()));
        positives.addAll(orEmpty(monitor.getCompetitorWords()));
        positives.addAll(orEmpty(monitor.getExecutiveNames()));
        positives.removeIf(w -> w == null || w.isBlank());
        if (positives.isEmpty()) {
            return List.of();
        }
        boolean any = !"all".equalsIgnoreCase(monitor.getMatchMode());
        if (any) {
            for (String word : positives) {
                if (text.contains(normalize(word))) {
                    matched.add(word.trim());
                }
            }
            if (matched.isEmpty()) {
                return List.of();
            }
        } else {
            int hit = 0;
            for (String word : positives) {
                if (text.contains(normalize(word))) {
                    matched.add(word.trim());
                    hit++;
                }
            }
            if (hit < positives.size()) {
                return List.of();
            }
        }
        return new ArrayList<>(matched);
    }

    public static String normalize(String value) {
        return (value == null ? "" : value).toLowerCase().replaceAll("\\s+", "");
    }

    public static String trim(String value, int max) {
        if (value == null) {
            return "";
        }
        String v = value.trim();
        return v.length() > max ? v.substring(0, max) : v;
    }

    public static String sha256(String value) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest((value == null ? "" : value).getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(hash.length * 2);
            for (byte b : hash) {
                sb.append(String.format("%02x", b));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    public static String contentHash(String title, String content, String url) {
        String normalized = normalize(title) + "\n" + normalize(content);
        if (normalized.isEmpty()) {
            normalized = normalize(url);
        }
        return sha256(normalized);
    }

    private static List<String> orEmpty(List<String> values) {
        return values == null ? List.of() : values;
    }
}
