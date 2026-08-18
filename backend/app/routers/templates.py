"""模板管理接口。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Template
from ..schemas import TemplateCreate, TemplateOut
from ..services.template_loader import load_styles, validate_template

router = APIRouter()


@router.get("", response_model=list[TemplateOut])
def list_templates(
    category: str | None = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    """模板列表，可按分类过滤。"""
    q = db.query(Template)
    if category:
        q = q.filter(Template.category == category)
    if active_only:
        q = q.filter(Template.is_active.is_(True))
    return q.order_by(Template.id).all()


@router.get("/styles")
def list_styles():
    """可用文风配置 + 发布渠道映射。"""
    return load_styles()


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db)):
    tpl = db.get(Template, template_id)
    if not tpl:
        raise HTTPException(404, "模板不存在")
    return tpl


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    """新增/导入企业自定义模板。"""
    errs = validate_template(payload.template_schema)
    if errs:
        raise HTTPException(422, detail={"message": "模板格式校验失败", "errors": errs})
    if db.query(Template).filter(Template.name == payload.name).first():
        raise HTTPException(409, "同名模板已存在")
    tpl = Template(
        name=payload.name,
        category=payload.category,
        schema_=payload.template_schema,
        is_builtin=False,
        is_active=payload.is_active,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.post("/{template_id}/toggle", response_model=TemplateOut)
def toggle_template(template_id: int, db: Session = Depends(get_db)):
    """启用/停用模板。"""
    tpl = db.get(Template, template_id)
    if not tpl:
        raise HTTPException(404, "模板不存在")
    tpl.is_active = not tpl.is_active
    db.commit()
    db.refresh(tpl)
    return tpl
