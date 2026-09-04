"""FastAPI 应用入口。"""
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import Base, SessionLocal, engine
from .observability import configure_logging, install_observability
from .routers import drafts, exports, intelligence, materials, policy, policy_aliases, qualification, templates
from .security import require_internal_token
from .services.template_loader import load_seed_templates, load_styles
from .opinion import models_ai  # noqa: F401  登记 AI 记录表供 create_all
from .opinion.routers import internal_router as opinion_internal_router
from .meeting import models_ai as meeting_models_ai  # noqa: F401
from .meeting.routers import ai_router as meeting_ai_router
from .meeting.routers import internal_router as meeting_internal_router

# 统一 UTF-8：确保 Windows 控制台/日志输出中文不乱码（PEP 540 之前的 locale 编码问题）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 确保所有业务表存在（含 style_config），幂等
    Base.metadata.create_all(bind=engine)
    # 启动时灌入内置种子模板（upsert，幂等）
    db = SessionLocal()
    try:
        load_seed_templates(db)
        load_styles(db)  # 初始化文风配置（无则从 styles.json 种子入库）
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
app.include_router(exports.router, prefix="/api/exports", tags=["exports"])
app.include_router(policy.router, prefix="/api/policy", tags=["policy"])
app.include_router(policy_aliases.router, prefix="/api/chat", tags=["policy"])
app.include_router(policy_aliases.router, prefix="/api/compliance", tags=["compliance"])
app.include_router(qualification.router, tags=["qualification-internal"])
app.include_router(intelligence.router, prefix="/api", tags=["intelligence"])
app.include_router(intelligence.internal_router, tags=["internal-intelligence"])
app.include_router(opinion_internal_router, tags=["internal-opinion"])
app.include_router(meeting_internal_router, tags=["internal-meeting"])
app.include_router(meeting_ai_router, prefix="/api/meeting/ai", tags=["meeting-ai"])

# 静态文件：导出文件与上传素材下载
app.mount("/static/exports", StaticFiles(directory=str(settings.export_path)), name="exports")
app.mount("/static/uploads", StaticFiles(directory=str(settings.upload_path)), name="uploads")

# 可观测性：traceId 中间件 + /metrics（Q13）
configure_logging()
install_observability(app)


@app.get("/api/health")
def health():
    return {"status": "ok", "env": settings.app_env}


@app.get("/internal/health", dependencies=[Depends(require_internal_token)])
def internal_health():
    return {"status": "ok", "service": "ai-server", "env": settings.app_env}
