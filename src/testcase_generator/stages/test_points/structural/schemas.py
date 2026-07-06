"""权限矩阵 / 状态机 结构化定义 schema（LLM 抽取输出）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Grant(BaseModel):
    role: str
    resource: str
    operation: str = Field(default="访问", description="操作，如 增删改查/改他人")
    effect: Literal["allow", "deny"] = "allow"
    source_quote: str = Field(default="", description="PRD 原文依据")


class PermissionMatrix(BaseModel):
    roles: list[str] = Field(default_factory=list)
    resources: list[str] = Field(default_factory=list)
    grants: list[Grant] = Field(default_factory=list)


class Transition(BaseModel):
    src: str
    dst: str
    event: str = ""
    guard: str = ""
    source_quote: str = Field(default="")


class StateMachine(BaseModel):
    name: str
    states: list[str] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
