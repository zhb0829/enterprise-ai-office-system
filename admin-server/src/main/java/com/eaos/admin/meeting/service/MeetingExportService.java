package com.eaos.admin.meeting.service;

import com.eaos.admin.meeting.entity.ConferenceReport;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.List;

import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.apache.poi.xwpf.usermodel.XWPFPicture;
import org.apache.poi.xwpf.usermodel.XWPFRun;

/** 纪要 Markdown → Word 导出（标题/多级标题/列表/段落）。 */
@Service
@RequiredArgsConstructor
public class MeetingExportService {

    public byte[] exportReportDocx(ConferenceReport report, String conferenceName) {
        try (XWPFDocument docx = new XWPFDocument(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            XWPFParagraph title = docx.createParagraph();
            title.setStyle("Title");
            title.createRun().setText(conferenceName + " — 会议纪要（v" + report.getVersion() + "）");

            for (String rawLine : report.getContent().split("\\R")) {
                String line = rawLine.strip();
                if (line.isEmpty()) {
                    continue;
                }
                if (line.startsWith("### ")) {
                    addHeading(docx, "Heading3", line.substring(4));
                } else if (line.startsWith("## ")) {
                    addHeading(docx, "Heading2", line.substring(3));
                } else if (line.startsWith("# ")) {
                    addHeading(docx, "Heading1", line.substring(2));
                } else if (line.startsWith("- ") || line.startsWith("* ")) {
                    XWPFParagraph paragraph = docx.createParagraph();
                    paragraph.setStyle("ListBullet");
                    paragraph.createRun().setText(line.substring(2));
                } else if (line.matches("^\\d+\\.\\s.*")) {
                    XWPFParagraph paragraph = docx.createParagraph();
                    paragraph.setStyle("ListNumber");
                    paragraph.createRun().setText(line.replaceFirst("^\\d+\\.\\s", ""));
                } else {
                    XWPFParagraph paragraph = docx.createParagraph();
                    paragraph.createRun().setText(line.replace("**", ""));
                }
            }
            docx.write(out);
            return out.toByteArray();
        } catch (IOException ex) {
            throw new IllegalStateException("生成 DOCX 失败", ex);
        }
    }

    private void addHeading(XWPFDocument docx, String style, String text) {
        XWPFParagraph heading = docx.createParagraph();
        heading.setStyle(style);
        XWPFRun run = heading.createRun();
        run.setText(stripMarkdownEmphasis(text));
    }

    private String stripMarkdownEmphasis(String text) {
        return text.replace("**", "").replace("*", "").replace("`", "");
    }
}
