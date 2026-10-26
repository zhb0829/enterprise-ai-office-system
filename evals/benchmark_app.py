"""Isolated benchmark entrypoint; never point this at the business database."""
import os
import time
import uuid
from contextlib import asynccontextmanager
from threading import Lock

from app import main
from app.db import SessionLocal
from .run import seed_corpus

active = 0
peak = 0
lock = Lock()
# 进程身份：用于证明验收期间"只热切换、不重启"
PROCESS_TOKEN = uuid.uuid4().hex
STARTED_AT = time.time()
original_lifespan = main.lifespan


@asynccontextmanager
async def lifespan(app):
    async with original_lifespan(app):
        with SessionLocal() as db:
            seed_corpus(db)
        yield


app = main.app
app.router.lifespan_context = lifespan


@app.middleware("http")
async def concurrency_probe(request, call_next):
    global active, peak
    if request.url.path.startswith("/benchmark/"):
        return await call_next(request)
    with lock:
        active += 1
        peak = max(peak, active)
    try:
        return await call_next(request)
    finally:
        with lock:
            active -= 1


@app.get("/benchmark/concurrency")
def concurrency():
    global peak
    with lock:
        result = {"peak_server_inflight": peak, "active": active}
        peak = active
        return result


@app.get("/benchmark/tenants")
def tenants():
    """G3 探针：租户在飞请求与耗时链路容量池占用（仅压测入口暴露）。"""
    from app.services import capacity

    guard = getattr(app.state, "resource_guard", None)
    return {
        "tenants": guard.snapshot() if guard is not None else None,
        "capacity": capacity.snapshot(),
    }


@app.get("/benchmark/identity")
def identity():
    """进程身份探针：同一进程内 token 不变，重启即变（G5 热切换验收用）。"""
    return {
        "processToken": PROCESS_TOKEN,
        "pid": os.getpid(),
        "startedAt": STARTED_AT,
        "uptimeSeconds": round(time.time() - STARTED_AT, 3),
    }
