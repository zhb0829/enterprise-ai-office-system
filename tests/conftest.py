"""测试全局环境：为内部鉴权测试注入非默认服务间令牌。

生产加固后，生产环境拒绝默认/弱令牌（见 app/config.py）。
本地 .env 与 CI 若不注入，内部鉴权用例会因令牌为空而 403。
此处仅在环境变量缺失时兜底（真实部署可通过环境变量覆盖）。
注意：必须在 import app.* 之前执行，故放在模块顶层，而非 fixture。
"""
import os

_INTERNAL_TOKEN_DEFAULTS = {
    "AI_INTERNAL_TOKEN": "ai-internal-token-0123456789abcdef",
    "OPINION_JAVA_TOKEN": "opinion-java-token-0123456789abcdef",
    "OPINION_INTERNAL_TOKEN": "opinion-internal-token-0123456789abcdef",
    "MEETING_JAVA_TOKEN": "meeting-java-token-0123456789abcdef",
    "MEETING_INTERNAL_TOKEN": "meeting-internal-token-0123456789abcdef",
}

for _name, _value in _INTERNAL_TOKEN_DEFAULTS.items():
    os.environ.setdefault(_name, _value)

# G3 租户限流：单元测试直连服务、没有网关流量整形需求，默认关闭以免与既有用例互相干扰；
# 限流与容量池行为由 tests/test_g3_limits.py 用显式配置覆盖验证。
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")


def trusted_headers(permissions):
    from app.config import settings
    return {
        "X-Internal-Token": settings.ai_internal_token,
        "X-User-Id": "test-user", "X-Tenant-Id": "default",
        "X-User-Permissions": permissions,
    }
