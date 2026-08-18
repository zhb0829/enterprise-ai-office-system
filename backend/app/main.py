"""FastAPI 应用入口。"""
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import SessionLocal
from .routers import drafts, materials, templates
from .services.template_loader import load_seed_templates

# 统一 UTF-8：确保 Windows 控制台/日志输出中文不乱码（PEP 540 之前的 locale 编码问题）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时灌入内置种子模板（upsert，幂等）
    db = SessionLocal()
    try:
        load_seed_templates(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="企业AI智能办公助手 - 公告与新闻稿智能撰写",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(templates.router, prefix="/api/templates", tags=["templates"])
app.include_router(drafts.router, prefix="/api/drafts", tags=["drafts"])
app.include_router(materials.router, prefix="/api/materials", tags=["materials"])

# 静态文件：导出文件与上传素材下载
app.mount("/static/exports", StaticFiles(directory=str(settings.export_path)), name="exports")
app.mount("/static/uploads", StaticFiles(directory=str(settings.upload_path)), name="uploads")


@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.app_env}
