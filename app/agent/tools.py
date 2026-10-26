from __future__ import annotations

from fastapi.encoders import jsonable_encoder

from .. import db as app_db
from ..schemas import ExportRequest, GenerateRequest, PolicyQuery
from .registry import ToolDefinition, registry


OBJECT = {"type": "object"}


def search_policy(payload):
    from ..services.policy import citation_for, search_policy_clauses
    request = PolicyQuery.model_validate(payload)
    with app_db.SessionLocal() as db:
        hits = search_policy_clauses(
            db, request.question, industry=request.industry, level=request.level,
            authority=request.authority, region=request.region, policy_name=request.policyName,
            as_of=request.asOf, limit=request.limit,
        )
        return {"citations": jsonable_encoder([citation_for(row) for row in hits])}


def retrieve_materials(payload):
    from ..services.materials import search_material_chunks
    with app_db.SessionLocal() as db:
        return {"chunks": jsonable_encoder(search_material_chunks(db, payload["query"], payload.get("materialIds") or [], limit=payload.get("limit", 8)))}


def verify_facts(payload):
    from ..services.factcheck import run_factcheck
    from ..services.llm import LLMClient
    return {"report": run_factcheck(payload["content"], payload.get("elements", []), payload.get("materials", ""), LLMClient())}


def extract_meeting_items(payload):
    from ..meeting.generation import extract_insights
    return {"insights": extract_insights(payload["materials"])}


def generate_announcement(payload):
    from ..routers.drafts import generate_news
    with app_db.SessionLocal() as db:
        return jsonable_encoder(generate_news(GenerateRequest.model_validate(payload), db))


def export_word_document(payload):
    from ..routers.drafts import export
    with app_db.SessionLocal() as db:
        request = ExportRequest.model_validate({**payload, "format": "docx"})
        return jsonable_encoder(export(request, db))


def install_tools():
    if registry.definitions:
        return
    registry.register(ToolDefinition(
        "search_policy", "Hybrid retrieval of valid policy clauses", PolicyQuery.model_json_schema(),
        {"type": "object", "required": ["citations"], "properties": {"citations": {"type": "array"}}, "additionalProperties": False},
        "policy:read", timeout=20,
    ), search_policy)
    registry.register(ToolDefinition(
        "retrieve_materials", "Retrieve approved reference material chunks",
        {"type": "object", "required": ["query"], "properties": {"query": {"type": "string", "minLength": 2}, "materialIds": {"type": "array", "items": {"type": "integer"}}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, "additionalProperties": False},
        {"type": "object", "required": ["chunks"], "properties": {"chunks": {"type": "array"}}, "additionalProperties": False},
        "materials:read", timeout=20,
    ), retrieve_materials)
    registry.register(ToolDefinition(
        "verify_facts", "Verify every claim against locatable evidence",
        {"type": "object", "required": ["content"], "properties": {"content": {"type": "string", "maxLength": 100000}, "elements": {"type": "array", "items": {"type": "object"}}, "materials": {"type": "string", "maxLength": 100000}}, "additionalProperties": False},
        {"type": "object", "required": ["report"], "properties": {"report": {"type": "array"}}, "additionalProperties": False},
        "draft:verify", timeout=30,
    ), verify_facts)
    registry.register(ToolDefinition(
        "extract_meeting_items", "Extract meeting insights from parsed materials",
        {"type": "object", "required": ["materials"], "properties": {"materials": {"type": "array", "items": {"type": "object"}, "maxItems": 50}}, "additionalProperties": False},
        {"type": "object", "required": ["insights"], "properties": {"insights": {"type": "array"}}, "additionalProperties": False},
        "meeting:read", timeout=30,
    ), extract_meeting_items)
    registry.register(ToolDefinition(
        "generate_announcement", "Generate a draft with claim-level evidence; never publish",
        GenerateRequest.model_json_schema(),
        {"type": "object", "required": ["draft", "versionId", "factCheckReport"], "properties": {
            "draft": {"type": "string", "minLength": 1}, "versionId": {"type": "string"},
            "factCheckReport": {"type": "array"},
        }},
        "draft:write", timeout=30, idempotency="process_key",
    ), generate_announcement)
    registry.register(ToolDefinition(
        "export_word_document", "Export an existing draft as DOCX, without changing review state",
        {"type": "object", "required": ["draftId"], "properties": {"draftId": {"type": "string", "minLength": 1}}, "additionalProperties": False},
        {"type": "object", "required": ["download_url", "format"], "properties": {"download_url": {"type": "string"}, "format": {"const": "docx"}}},
        "draft:write", timeout=15, idempotency="process_key",
    ), export_word_document)


SKILLS = [
    {"name": "policy_qa", "version": "2.0.0", "tools": ["search_policy"], "permission": "policy:read", "prompt_version": "policy-answer-v2"},
    {"name": "announcement", "version": "2.0.0", "tools": ["retrieve_materials", "generate_announcement", "verify_facts", "export_word_document"], "permission": "draft:write", "human_review": True},
    {"name": "meeting", "version": "1.0.0", "tools": ["extract_meeting_items", "search_policy"], "permission": "meeting:read"},
]
