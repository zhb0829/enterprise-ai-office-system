from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import HTTPException

from .governance import Principal, principal_var
from .runtime import current_run, snapshot, step


@dataclass
class TaskContext:
    intent: str
    payload: dict
    principal: Principal = field(default_factory=principal_var.get)
    memory: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPlan:
    intent: str
    stages: tuple[str, ...] = ("planner", "retriever", "actor", "verifier")
    required_permission: str = ""
    required_fields: tuple[str, ...] = ()


class Planner(ABC):
    @abstractmethod
    def plan(self, context: TaskContext) -> ExecutionPlan: ...


class Retriever(ABC):
    @abstractmethod
    def retrieve(self, context: TaskContext, plan: ExecutionPlan) -> Any: ...


class Actor(ABC):
    @abstractmethod
    def act(self, context: TaskContext, plan: ExecutionPlan, evidence: Any) -> dict: ...


class Verifier(ABC):
    @abstractmethod
    def verify(self, context: TaskContext, plan: ExecutionPlan, evidence: Any, result: dict) -> dict: ...


class WorkflowPlanner(Planner):
    def __init__(self, *, permission="", required_fields=()):
        self.permission = permission
        self.required_fields = tuple(required_fields)

    def plan(self, context):
        if context.principal.authenticated and self.permission:
            context.principal.require(self.permission)
        missing = [key for key in self.required_fields if not context.payload.get(key)]
        if missing:
            raise HTTPException(422, {"missing": missing})
        return ExecutionPlan(context.intent, required_permission=self.permission, required_fields=self.required_fields)


class FunctionRetriever(Retriever):
    def __init__(self, handler: Callable):
        self.handler = handler

    def retrieve(self, context, plan):
        return self.handler(context)


class FunctionActor(Actor):
    def __init__(self, handler: Callable):
        self.handler = handler

    def act(self, context, plan, evidence):
        return self.handler(context, evidence)


class EvidenceVerifier(Verifier):
    def __init__(self, handler: Callable):
        self.handler = handler

    def verify(self, context, plan, evidence, result):
        if context.principal.authenticated and plan.required_permission:
            context.principal.require(plan.required_permission)
        report = self.handler(context, evidence, result)
        if capture := current_run.get():
            capture.verification.update(snapshot(report))
        if report.get("passed") is False:
            raise HTTPException(422, {"message": "verification failed", "verification": snapshot(report)})
        return report


class AgentPipeline:
    def __init__(self, planner: Planner, retriever: Retriever, actor: Actor, verifier: Verifier):
        self.planner, self.retriever, self.actor, self.verifier = planner, retriever, actor, verifier

    def execute(self, context: TaskContext):
        with step("planner", inputs={"intent": context.intent, "fields": list(context.payload)}) as record:
            plan = self.planner.plan(context)
            record["output"] = {"stages": list(plan.stages), "required_permission": plan.required_permission}
            if capture := current_run.get():
                capture.plan = list(plan.stages)
        with step("retriever", inputs={"intent": context.intent}) as record:
            evidence = self.retriever.retrieve(context, plan)
            record["output"] = {"type": type(evidence).__name__, "count": len(evidence) if hasattr(evidence, "__len__") else None}
        with step("actor", inputs={"intent": context.intent}) as record:
            result = self.actor.act(context, plan, evidence)
            record["output"] = result
        with step("verifier", inputs={"permission": plan.required_permission}) as record:
            report = self.verifier.verify(context, plan, evidence, result)
            record["output"] = report
            if capture := current_run.get():
                capture.verification.update(report)
        return result
