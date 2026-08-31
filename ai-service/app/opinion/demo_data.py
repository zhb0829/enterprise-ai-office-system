"""可重复运行的舆情本地演示数据。"""
from __future__ import annotations

from datetime import datetime, timedelta


DEMO_MONITOR = {
    "name": "舆情演示监控",
    "enterpriseName": "星河科技",
    "brandWords": ["星河科技"],
    "competitorWords": ["云海科技"],
    "executiveNames": [],
    "excludeWords": [],
    "matchMode": "any",
    "timeWindowDays": 7,
    "status": "enabled",
}


DEMO_RESPONSE_CASES = [
    {
        "title": "产品质量投诉集中曝光处置参考案例",
        "eventType": "产品质量投诉",
        "riskLevel": "预警",
        "strategy": "先核实投诉批次、产品型号和安全风险；由客服、质量和法务统一口径，在确认事实前不作原因归责。",
        "content": "2 小时内建立专项群，汇总投诉证据和订单信息；对受影响用户开通专线并说明受理时限；如确认存在批次问题，发布分批公告、退换或召回安排，并按监管要求留存处置记录。",
        "effect": "投诉回应时效提升，重复咨询减少；后续根据核查结果持续更新公开说明。",
        "tags": ["产品质量", "投诉", "公开回应", "召回"],
        "source": "本地演示参考",
    },
    {
        "title": "负面舆情多平台扩散处置参考案例",
        "eventType": "负面舆情扩散",
        "riskLevel": "预警",
        "strategy": "以事实核验和用户权益保障为优先，区分已证实信息、待核实信息和不实信息，避免用单一声明替代持续沟通。",
        "content": "跟踪首发内容和主要转载渠道，记录传播时间线；发布简明进展说明与咨询入口；对高频问题形成统一答复；每 4 小时评估新增投诉、媒体问询和跨平台传播变化。",
        "effect": "形成可追溯的回应节奏，降低信息真空造成的二次传播风险。",
        "tags": ["负面舆情", "传播", "事实核验", "用户沟通"],
        "source": "本地演示参考",
    },
    {
        "title": "监管关注与消费者投诉并发处置参考案例",
        "eventType": "监管关注",
        "riskLevel": "危机",
        "strategy": "同步启动合规核查和客户保障流程，所有对外信息须经业务、法务和合规复核，避免披露未经确认的调查结论。",
        "content": "明确事件负责人和对外发言人；固定证据、业务记录和用户诉求；主动评估监管报送义务；向受影响用户说明补救路径和处理节点；每日复盘风险变化及整改进度。",
        "effect": "保证监管沟通、用户补救和内部整改记录一致，便于后续审计与复盘。",
        "tags": ["监管", "合规", "消费者投诉", "整改"],
        "source": "本地演示参考",
    },
]


def build_demo_articles(run_tag: str, now: datetime | None = None) -> list[dict]:
    """生成覆盖负面/正面/中性/转载关系的四篇文章。"""
    current = now or datetime.now().replace(microsecond=0)
    return [
        {
            "title": "星河科技产品质量问题被曝光",
            "content": (
                f"多位消费者投诉星河科技产品存在质量问题，监管部门已立案调查。"
                f"本地演示批次：{run_tag}。"
            ),
            "url": f"https://example.com/opinion-demo/{run_tag}/quality-1",
            "author": "演示媒体甲",
            "publishTime": (current - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "title": "星河科技产品质量问题被曝光",
            "content": (
                f"本文转载自《星河科技产品质量问题被曝光》，消费者投诉产品存在缺陷，"
                f"相关部门持续关注。本地演示批次：{run_tag}。"
            ),
            "url": f"https://example.com/opinion-demo/{run_tag}/quality-2",
            "author": "演示媒体乙",
            "publishTime": (current - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "title": "星河科技新品发布获市场好评",
            "content": (
                f"星河科技新品获得市场好评，营收增长并完成重要战略合作。"
                f"本地演示批次：{run_tag}。"
            ),
            "url": f"https://example.com/opinion-demo/{run_tag}/positive",
            "author": "演示媒体丙",
            "publishTime": (current - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "title": "星河科技年度战略发布会召开",
            "content": (
                f"星河科技发布未来一年的战略方向与业务布局规划。"
                f"本地演示批次：{run_tag}。"
            ),
            "url": f"https://example.com/opinion-demo/{run_tag}/neutral",
            "author": "演示媒体丁",
            "publishTime": current.strftime("%Y-%m-%d %H:%M:%S"),
        },
    ]


def build_demo_source(run_tag: str) -> dict:
    """返回一个仅用于手工灌入演示数据的公开来源配置。"""
    return {
        "name": f"舆情演示来源-{run_tag}",
        "sourceType": "web",
        "platform": "demo",
        "homepage": f"https://example.com/opinion-demo/{run_tag}",
        "collectMethod": "http",
        "frequency": "manual",
        "rateLimit": "1/min",
        "priority": 100,
        "adapterVersion": "demo-v1",
        "status": "enabled",
    }
