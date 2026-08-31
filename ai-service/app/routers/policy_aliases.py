"""与详细设计文档一致的兼容入口，内部仍复用 policy 服务。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import ComplianceRequest, ComplianceResponse, PolicyAnswer, PolicyQuery
from ..services.policy import answer_policy, check_compliance

router = APIRouter()


@router.post("/policy", response_model=PolicyAnswer)
def chat_policy(request: PolicyQuery, db: Session = Depends(get_db)):
    return answer_policy(db, request)


@router.post("/check", response_model=ComplianceResponse)
def check_policy(request: ComplianceRequest, db: Session = Depends(get_db)):
    return check_compliance(db, request)
