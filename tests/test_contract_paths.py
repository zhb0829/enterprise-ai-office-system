"""契约守护：锁定 Java ⇄ Python 稳定内部路径，防止意外改名破坏契约。"""
from app.main import app

STABLE_INTERNAL_PATHS = {
    # Java → Python
    "/internal/health",
    "/internal/intelligence/tasks/{task_id}/dispatch",
    "/internal/intelligence/reports/generate",
    # Python → Java 的情报权威数据面由 Java 侧守护（/internal/intelligence/**）
    # 舆情/会议模块内部面
    "/internal/opinion/ping",
    "/internal/meeting/ping",
}


def _all_paths(routes):
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _all_paths(getattr(original, "routes", []) or [])
            continue
        if hasattr(route, "path"):
            yield route.path
        for child in getattr(route, "routes", []) or []:
            yield from _all_paths([child])


def test_stable_internal_paths_registered():
    registered = set(_all_paths(app.routes))
    missing = STABLE_INTERNAL_PATHS - registered
    assert not missing, f"缺少契约内部端点: {sorted(missing)}"
