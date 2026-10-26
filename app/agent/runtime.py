from __future__ import annotations

import hashlib
import inspect
import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps

from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from .. import db as app_db
from ..observability import trace_id_var, user_id_var
from .models import AgentRun
from .governance import DataLevel, data_level_var, principal_var, redact

logger = logging.getLogger(__name__)
current_run: ContextVar["RunCapture | None"] = ContextVar("agent_run", default=None)
current_step: ContextVar[str] = ContextVar("agent_step", default="")
SENSITIVE_KEYS = {
    "password", "token", "api_key", "apikey", "authorization", "x-internal-token",
    "access_token", "refresh_token", "secret", "client_secret", "llm_api_key",
    "embedding_api_key", "rerank_api_key", "cookie", "set-cookie",
}


def snapshot(value):
    """Bounded snapshots keep secrets out of audit records."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in SENSITIVE_KEYS else snapshot(item)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple)):
        return [snapshot(item) for item in value[:100]]
    if isinstance(value, str):
        return redact(value[:16000])
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if hasattr(value, "model_dump"):
        return snapshot(value.model_dump(mode="json"))
    if isinstance(value, datetime):
        return value.isoformat()
    return {"type": type(value).__name__}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


@dataclass
class RunCapture:
    intent: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = field(default_factory=lambda: trace_id_var.get() or uuid.uuid4().hex)
    user_id: str = field(default_factory=lambda: user_id_var.get() or principal_var.get().user_id or "service-worker")
    session_id: str = ""
    tenant_id: str = field(default_factory=lambda: principal_var.get().tenant_id or "default")
    department_id: str = field(default_factory=lambda: principal_var.get().department_id)
    classification: DataLevel = field(default_factory=data_level_var.get)
    memory: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)
    plan: list = field(default_factory=list)
    verification: dict = field(default_factory=dict)
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0, "cost": None, "usage_complete": True})
    # G4：路由决策汇总；由 app/services/model_router.py 累加，随 AgentRun 落库
    routing: dict = field(default_factory=lambda: {
        "enabled": False, "routedCalls": 0,
        "tiers": {}, "models": {}, "sources": {}, "decisions": [],
    })
    lock: threading.Lock = field(default_factory=threading.Lock)


@contextmanager
def step(name: str, *, inputs=None, tool="", model="", prompt_version=""):
    run = current_run.get()
    if run:
        run.classification = max(run.classification, data_level_var.get())
    record = {
        "step_id": uuid.uuid4().hex, "parent_step_id": current_step.get(),
        "name": name, "tool": tool, "model": model, "prompt_version": prompt_version,
        "input": snapshot(inputs), "output": None, "evidence": [], "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(), "usage": {},
    }
    started = time.perf_counter()
    token = current_step.set(record["step_id"])
    try:
        yield record
        record["status"] = "completed"
    except BaseException as exc:
        record["status"] = "failed"
        record["error"] = type(exc).__name__
        raise
    finally:
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        record["output"] = snapshot(record["output"])
        record["evidence"] = snapshot(record["evidence"])
        current_step.reset(token)
        if run:
            with run.lock:
                run.classification = max(run.classification, data_level_var.get())
                run.steps.append(record)


def traced(name=None, *, prompt_version=""):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with step(name or fn.__name__, inputs=kwargs, prompt_version=prompt_version) as record:
                result = fn(*args, **kwargs)
                record["output"] = result
                return result
        return wrapped
    return decorate


def context_call(fn, *args, **kwargs):
    context = copy_context()
    return lambda: context.run(fn, *args, **kwargs)


def agent_stream(intent: str, db: Session, request=None):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            context = copy_context()

            def execute():
                session_id = getattr(request, "sessionId", "") or ""
                capture = RunCapture(intent=intent, session_id=session_id)
                p = principal_var.get()
                if session_id and p.authenticated and not p.public_only and "memory:read" in p.permissions:
                    from .memory import MemoryStore
                    capture.memory = MemoryStore(db).context(session_id)
                    db.commit()
                token = current_run.set(capture)
                started = time.perf_counter()
                started_at = datetime.now(timezone.utc).replace(tzinfo=None)
                status, error, result = "completed", "", {}
                try:
                    for chunk in fn(*args, **kwargs):
                        if isinstance(chunk, str) and chunk.startswith("data: "):
                            try:
                                event = json.loads(chunk[6:])
                                if event.get("type") == "error":
                                    status, error = "failed", "stream_error"
                                if event.get("type") == "done":
                                    result = event
                            except ValueError:
                                pass
                        yield chunk
                except GeneratorExit:
                    status, error = "cancelled", "client_disconnected"
                    raise
                except BaseException as exc:
                    status, error = "failed", type(exc).__name__
                    raise
                finally:
                    current_run.reset(token)
                    if status != "completed":
                        db.rollback()
                    audit_db = db if status == "completed" else Session(bind=db.get_bind())
                    try:
                        data_level_var.set(max(capture.classification, data_level_var.get()))
                        if status == "completed":
                            _remember_result(audit_db, p, session_id, request, result)
                        audit_db.add(AgentRun(
                            run_id=capture.run_id, trace_id=capture.trace_id, user_id=capture.user_id,
                            session_id=capture.session_id, tenant_id=capture.tenant_id,
                            department_id=capture.department_id, intent=intent, status=status, plan=capture.plan,
                            classification=max(DataLevel.internal, capture.classification, data_level_var.get()).name,
                            steps=capture.steps, verification_result=snapshot(capture.verification),
                            final_answer=snapshot(result), usage=capture.usage, routing=capture.routing,
                            error=error,
                            latency_ms=round((time.perf_counter() - started) * 1000),
                            started_at=started_at, finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        ))
                        audit_db.commit()
                    finally:
                        if audit_db is not db:
                            audit_db.close()

            iterator = execute()
            try:
                while True:
                    try:
                        chunk = context.run(next, iterator)
                    except StopIteration:
                        break
                    yield chunk
            finally:
                context.run(iterator.close)
        return wrapped
    return decorate


def agent_run(intent: str, plan=()):
    def decorate(fn):
        signature = inspect.signature(fn)

        @wraps(fn)
        def wrapped(*args, **kwargs):
            if current_run.get():
                return fn(*args, **kwargs)
            bound = signature.bind(*args, **kwargs).arguments
            request = bound.get("request") or bound.get("payload")
            session_id = getattr(request, "sessionId", "")
            if isinstance(request, dict):
                session_id = request.get("sessionId") or str(request.get("taskId") or "")
            capture = RunCapture(intent=intent, session_id=session_id, plan=list(plan))
            source_db = bound.get("db")
            p = principal_var.get()
            if session_id and p.authenticated and not p.public_only and "memory:read" in p.permissions:
                from .memory import MemoryStore
                if isinstance(source_db, Session):
                    capture.memory = MemoryStore(source_db).context(session_id)
                else:
                    with app_db.SessionLocal() as memory_db:
                        capture.memory = MemoryStore(memory_db).context(session_id)
                        memory_db.commit()
            token = current_run.set(capture)
            trace_token = trace_id_var.set(capture.trace_id)
            started = time.perf_counter()
            started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            result, error, status = None, "", "completed"
            try:
                result = fn(*args, **kwargs)
                if isinstance(result, dict):
                    result["runId"] = capture.run_id
                return result
            except BaseException as exc:
                status, error = "failed", type(exc).__name__
                raise
            finally:
                current_run.reset(token)
                trace_id_var.reset(trace_token)
                source_db = bound.get("db")
                # Reuse successful sessions: retaining a business connection while
                # requesting a second audit connection can deadlock a saturated pool.
                owns_session = not isinstance(source_db, Session) or bool(error)
                if isinstance(source_db, Session) and error:
                    source_db.rollback()
                audit_db = (
                    Session(bind=source_db.get_bind()) if isinstance(source_db, Session) and error
                    else source_db if isinstance(source_db, Session)
                    else app_db.SessionLocal()
                )
                try:
                    data_level_var.set(max(capture.classification, data_level_var.get()))
                    if status == "completed":
                        _remember_result(audit_db, p, session_id, request, result)
                    audit_db.add(AgentRun(
                        run_id=capture.run_id, trace_id=capture.trace_id, user_id=capture.user_id,
                        session_id=capture.session_id, tenant_id=capture.tenant_id,
                        department_id=capture.department_id, intent=intent, status=status, plan=capture.plan,
                        classification=max(DataLevel.internal, capture.classification, data_level_var.get()).name,
                        steps=capture.steps, verification_result=snapshot(capture.verification),
                        final_answer=snapshot(jsonable_encoder(result)) if result is not None else {},
                        usage=capture.usage, routing=capture.routing, error=error,
                        latency_ms=round((time.perf_counter() - started) * 1000),
                        started_at=started_at, finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    ))
                    audit_db.commit()
                except Exception:
                    audit_db.rollback()
                    logger.exception("Agent audit persistence failed run_id=%s", capture.run_id)
                    if not error:
                        raise
                finally:
                    if owns_session:
                        audit_db.close()
        return wrapped
    return decorate


def _remember_result(db, principal, session_id, request, result):
    if not (session_id and principal.authenticated and not principal.public_only and
            {"memory:read", "memory:write"} <= principal.permissions):
        return
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError
    from .memory import MemoryStore
    from .governance import audit
    payload = request.model_dump(mode="json") if hasattr(request, "model_dump") else request
    payload = payload if isinstance(payload, dict) else {}
    output = jsonable_encoder(result)
    output = output if isinstance(output, dict) else {}
    question = str(payload.get("question") or payload.get("eventDesc") or payload.get("instruction") or "")
    answer = str(output.get("answer") or output.get("draft") or output.get("content") or "")
    if not question or not answer:
        return
    try:
        with db.begin_nested():
            MemoryStore(db).remember_turn(session_id, question, answer)
    except (HTTPException, IntegrityError) as exc:
        if isinstance(exc, HTTPException) and exc.status_code != 409:
            raise
        audit(db, "memory.concurrent_turn", session_id, outcome="conflict")
