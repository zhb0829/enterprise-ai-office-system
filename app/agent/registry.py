from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextvars import copy_context
from dataclasses import asdict, dataclass, field
from threading import BoundedSemaphore, Lock
from typing import Callable

from jsonschema import Draft202012Validator, ValidationError

from .runtime import digest, snapshot, step
from .governance import principal_var


class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class RetryableToolError(Exception):
    """Only explicitly transient, read-only failures may be retried."""


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    permission: str
    timeout: float = 30
    retry_policy: dict = field(default_factory=lambda: {"max_attempts": 1})
    idempotency: str = "read_only"
    audit_policy: str = "redacted"
    version: str = "1.0.0"


class ToolRegistry:
    def __init__(self, max_workers=16):
        self.definitions: dict[str, ToolDefinition] = {}
        self.handlers: dict[str, Callable] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="agent-tool")
        self.capacity = BoundedSemaphore(max_workers)
        self.lock = Lock()
        self.cache = {}

    def register(self, definition: ToolDefinition, handler: Callable):
        if definition.name in self.definitions:
            raise ValueError(f"Duplicate tool: {definition.name}")
        Draft202012Validator.check_schema(definition.input_schema)
        Draft202012Validator.check_schema(definition.output_schema)
        if definition.timeout <= 0 or definition.idempotency not in {"read_only", "process_key"}:
            raise ValueError("Invalid tool execution policy")
        if not 1 <= int(definition.retry_policy.get("max_attempts", 1)) <= 5:
            raise ValueError("Invalid retry policy")
        self.definitions[definition.name] = definition
        self.handlers[definition.name] = handler

    def list(self):
        return [asdict(item) for item in self.definitions.values()]

    def invoke(self, name: str, payload: dict, *, permissions: set[str], principal: str, idempotency_key=""):
        definition = self.definitions.get(name)
        with step("tool.invoke", tool=name, inputs=payload) as audit:
            if not definition:
                raise ToolError("TOOL_NOT_FOUND", "Unknown tool")
            audit["version"] = definition.version
            if definition.permission not in permissions:
                raise ToolError("FORBIDDEN", "Tool permission denied")
            try:
                Draft202012Validator(definition.input_schema).validate(payload)
            except ValidationError as exc:
                raise ToolError("INVALID_INPUT", exc.message) from exc
            identity = principal_var.get()
            cache_key = (identity.tenant_id, identity.department_id, identity.public_only,
                         identity.clearance.name, principal, name, definition.version, idempotency_key)
            request_hash = digest(payload)
            if definition.idempotency == "process_key":
                if not idempotency_key:
                    raise ToolError("IDEMPOTENCY_REQUIRED", "Idempotency key required")
                with self.lock:
                    existing = self.cache.get(cache_key)
                    if existing:
                        if existing["hash"] != request_hash:
                            raise ToolError("IDEMPOTENCY_CONFLICT", "Key belongs to another input")
                        if existing["status"] != "completed":
                            raise ToolError("IN_PROGRESS", "Previous invocation is pending or indeterminate")
                        return existing["result"]
                    if len(self.cache) >= 10000:
                        raise ToolError("CAPACITY_EXCEEDED", "Idempotency store is full")
                    self.cache[cache_key] = {"hash": request_hash, "status": "pending"}
            if not self.capacity.acquire(blocking=False):
                if definition.idempotency == "process_key":
                    with self.lock:
                        self.cache.pop(cache_key, None)
                raise ToolError("CAPACITY_EXCEEDED", "Tool executor is busy")
            context = copy_context()
            deadline = time.monotonic() + definition.timeout

            def execute():
                attempts = int(definition.retry_policy.get("max_attempts", 1))
                for attempt in range(attempts):
                    try:
                        return self.handlers[name](payload)
                    except RetryableToolError:
                        if definition.idempotency != "read_only" or attempt + 1 == attempts:
                            raise
                        delay = min(0.1 * 2 ** attempt, 1)
                        if time.monotonic() + delay >= deadline:
                            raise
                        time.sleep(delay)

            future = self.executor.submit(context.run, execute)
            future.add_done_callback(lambda _: self.capacity.release())
            try:
                result = future.result(timeout=definition.timeout)
            except TimeoutError as exc:
                # Running Python threads cannot be killed; never retry unknown outcomes.
                future.cancel()
                audit["outcome"] = "indeterminate"
                raise ToolError("TOOL_TIMEOUT", "Deadline exceeded; outcome may be indeterminate") from exc
            except Exception as exc:
                raise ToolError("TOOL_FAILED", type(exc).__name__) from exc
            try:
                Draft202012Validator(definition.output_schema).validate(result)
            except ValidationError as exc:
                raise ToolError("INVALID_OUTPUT", exc.message) from exc
            audit["output"] = snapshot(result)
            if definition.idempotency == "process_key":
                with self.lock:
                    self.cache[cache_key].update(status="completed", result=result)
            return result


registry = ToolRegistry()
