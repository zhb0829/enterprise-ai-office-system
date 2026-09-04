"""舆情日报/周报生成与导出。

报告正文由 LLM 基于 Java 传入的结构化数据生成（引用证据必须来自输入数据）；
LLM 不可用时使用规则化模板拼装，保证离线可验收。PDF 导出依赖 pandoc/xelatex，
缺失时降级为可打印 HTML 文件。
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import shutil
import subprocess
import time
import urllib.parse
from datetime import datetime

from ..config import settings
from ..services.llm import LLMClient, LLMError

logger = logging.getLogger(__name__)

PROMPT_VERSION = "opinion-report-v1"


def generate_report(data: dict, period: str, monitor_id: int,
                    period_start: str, period_end: str) -> dict:
    model = "rule-based"
    prompt_version = PROMPT_VERSION
    summary, content_html, evidence = _rule_report(data, period, monitor_id, period_start, period_end)
    llm = LLMClient()
    if not llm.is_mock:
        try:
            context = _context_json(data, period, period_start, period_end)
            messages = [
                {"role": "system", "content": (
                    "你是企业舆情分析师。仅依据输入数据生成日报/周报，输出 JSON："
                    "{summary:string, contentHtml:string, evidence:string[]}。"
                    "contentHtml 为一段 HTML（可含 h3/p/ul/li/table），"
                    "必须使用输入中的事件、情感统计、告警与证据，不得编造事实。"
                )},
                {"role": "user", "content": context},
            ]
            start = time.time()
            raw = llm.chat_json(messages, model=settings.llm_model_generation)
            _ = time.time() - start
            summary = str(raw.get("summary") or summary)
            content_html = str(raw.get("contentHtml") or content_html)
            evidence = [str(e) for e in raw.get("evidence", []) or []]
            model = settings.llm_model_generation
        except (LLMError, ValueError, AttributeError) as exc:
            logger.warning("报告生成 LLM 失败，使用规则化模板: %s", exc)
    return {
        "summary": summary,
        "contentHtml": content_html,
        "model": model,
        "promptVersion": prompt_version,
        "evidence": evidence,
    }


def _rule_report(data: dict, period: str, monitor_id: int,
                 period_start: str, period_end: str) -> tuple[str, str, list[str]]:
    monitor = data.get("monitor") or ""
    sentiment = data.get("sentiment") or {}
    events = data.get("events") or []
    alerts = data.get("alerts") or []
    evidence = data.get("evidence") or []

    label = "周报" if period == "weekly" else "日报"
    summary = (f"{monitor} {label}：共 {data.get('articleCount', 0)} 篇文章，"
               f"正面 {sentiment.get('positive', 0)}、中性 {sentiment.get('neutral', 0)}、"
               f"负面 {sentiment.get('negative', 0)}，聚合热点事件 {len(events)} 个。")

    parts = [
        f"<h3>{html_lib.escape(summary)}</h3>",
        "<h4>情感分布</h4>",
        "<ul>",
        f"<li>正面：{sentiment.get('positive', 0)}</li>",
        f"<li>中性：{sentiment.get('neutral', 0)}</li>",
        f"<li>负面：{sentiment.get('negative', 0)}</li>",
        "</ul>",
    ]
    if events:
        parts.append("<h4>热点事件</h4><ul>")
        for event in events[:10]:
            title = html_lib.escape(str(event.get("title") or ""))
            risk = html_lib.escape(str(event.get("riskLevel") or "关注"))
            count = event.get("reportCount") or 0
            parts.append(f"<li><strong>{title}</strong>（风险：{risk}，{count} 篇）</li>")
        parts.append("</ul>")
    if alerts:
        parts.append("<h4>告警</h4><ul>")
        for alert in alerts[:10]:
            risk = html_lib.escape(str(alert.get("riskLevel") or ""))
            state = html_lib.escape(str(alert.get("state") or ""))
            parts.append(f"<li>等级 {risk} · 状态 {state}</li>")
        parts.append("</ul>")
    if evidence:
        parts.append("<h4>引用证据</h4><ul>")
        for item in evidence[:12]:
            title = html_lib.escape(str(item.get("title") or ""))
            url = html_lib.escape(str(item.get("url") or ""))
            link = f"<a href=\"{url}\" target=\"_blank\" rel=\"noreferrer\">{title}</a>" if url else title
            parts.append(f"<li>{link}</li>")
        parts.append("</ul>")

    content_html = "\n".join(parts)
    evidence_list = [str(item.get("url") or item.get("title") or "") for item in evidence[:12]]
    return summary, content_html, evidence_list


def _context_json(data: dict, period: str, period_start: str, period_end: str) -> str:
    import json

    payload = {
        "period": period,
        "periodStart": period_start,
        "periodEnd": period_end,
        "data": data,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)[:12000]


def export_pdf(report_id: int, title: str, content_html: str) -> dict:
    """生成 PDF（pandoc + xelatex）；缺失时降级为 HTML 文件，均返回下载地址。"""
    safe = re.sub(r"[\\/:*?\"<>|]", "_", title or "report")[:60] or "report"
    filename = f"{safe}_{report_id}.pdf"
    html_path = _save_html(report_id, safe, title, content_html)
    pdf_path = settings.upload_path / filename
    pandoc = shutil.which("pandoc")
    if pandoc:
        try:
            cmd = [
                pandoc, str(html_path), "-o", str(pdf_path),
                "--pdf-engine=xelatex",
                "-V", f"CJKmainfont={settings.pdf_chinese_font}",
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
            return {
                "downloadUrl": f"/api/files/upload/{urllib.parse.quote(filename)}",
                "format": "pdf",
                "reportId": report_id,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("报告 PDF 生成失败，降级 HTML: %s", exc)
    html_filename = f"{safe}_{report_id}.html"
    _write_html(settings.upload_path / html_filename, title, content_html)
    return {
        "downloadUrl": f"/api/files/upload/{urllib.parse.quote(html_filename)}",
        "format": "html",
        "reportId": report_id,
        "note": "本机未安装 pandoc/xelatex，已提供可打印 HTML 版本",
    }


def _save_html(report_id: int, safe: str, title: str, content_html: str):
    path = settings.upload_path / f"{safe}_{report_id}.md"
    path.write_text(content_html, encoding="utf-8")
    return path


def _write_html(path, title: str, content_html: str) -> None:
    body = (
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        f"<title>{html_lib.escape(title)}</title>"
        "<style>body{font-family:'Microsoft YaHei',sans-serif;max-width:820px;"
        "margin:32px auto;line-height:1.7;color:#1e293b;padding:0 16px}"
        "a{color:#0f5f59}h4{margin-top:20px}</style></head>"
        f"<body><h2>{html_lib.escape(title)}</h2>{content_html}</body></html>"
    )
    path.write_text(body, encoding="utf-8")