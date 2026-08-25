package com.eaos.admin.opinion.support;

import java.net.InetAddress;
import java.net.URI;
import java.net.UnknownHostException;
import java.util.Locale;

public final class OpinionUrlPolicy {

    private OpinionUrlPolicy() {
    }

    public static String validatePublicHttpUrl(String value) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("来源主页不能为空");
        }
        URI uri;
        try {
            uri = URI.create(value.trim());
        } catch (Exception e) {
            throw new IllegalArgumentException("来源 URL 格式不正确");
        }
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        String host = uri.getHost();
        if (!("http".equals(scheme) || "https".equals(scheme)) || host == null
                || host.isBlank() || uri.getUserInfo() != null) {
            throw new IllegalArgumentException("来源仅允许不带凭据的 http/https 公网地址");
        }
        String normalizedHost = host.toLowerCase(Locale.ROOT);
        if ("localhost".equals(normalizedHost) || normalizedHost.endsWith(".localhost")
                || normalizedHost.endsWith(".local") || normalizedHost.equals("0.0.0.0")
                || normalizedHost.equals("127.0.0.1") || normalizedHost.equals("::1")) {
            throw new IllegalArgumentException("来源地址禁止访问本机或本地域名");
        }
        try {
            for (InetAddress address : InetAddress.getAllByName(host)) {
                if (address.isAnyLocalAddress() || address.isLoopbackAddress()
                        || address.isLinkLocalAddress() || address.isSiteLocalAddress()
                        || address.isMulticastAddress()) {
                    throw new IllegalArgumentException("来源地址禁止访问内网、回环或链路本地地址");
                }
            }
        } catch (UnknownHostException e) {
            throw new IllegalArgumentException("来源域名无法解析");
        }
        return uri.toString();
    }
}
