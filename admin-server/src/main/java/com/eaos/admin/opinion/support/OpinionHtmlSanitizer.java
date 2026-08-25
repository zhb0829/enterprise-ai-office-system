package com.eaos.admin.opinion.support;

import org.jsoup.Jsoup;
import org.jsoup.safety.Safelist;

public final class OpinionHtmlSanitizer {

    private static final Safelist ALLOWED = new Safelist()
            .addTags("h3", "h4", "p", "ul", "ol", "li", "strong", "em",
                    "a", "table", "thead", "tbody", "tr", "th", "td", "br")
            .addAttributes("a", "href", "target", "rel")
            .addProtocols("a", "href", "http", "https");

    private OpinionHtmlSanitizer() {
    }

    public static String clean(String html) {
        return Jsoup.clean(html == null ? "" : html, "", ALLOWED,
                new org.jsoup.nodes.Document.OutputSettings().prettyPrint(false));
    }
}
