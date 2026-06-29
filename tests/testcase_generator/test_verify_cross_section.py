"""verify 跨族 + 跨条款矛盾扫描 单测。"""

from __future__ import annotations

import json

import pytest

from src.testcase_generator.services.llm_client import LLMClient


async def test_generate_structured_passes_explicit_model(monkeypatch):
    """传入 model 时，_call 必须收到该 model（而非 primary）。"""
    from pydantic import BaseModel

    class _Out(BaseModel):
        ok: bool

    client = LLMClient.__new__(LLMClient)  # 跳过 __init__ 避免连真网关
    client.primary_model = "claude-primary"
    client._json_mode = False

    seen = {}

    async def fake_call(model, system_prompt, user_content, output_schema, temperature, images=None):
        seen["model"] = model
        return _Out(ok=True)

    monkeypatch.setattr(client, "_call", fake_call)

    await client.generate_structured("sys", "usr", _Out, model="deepseek-x")
    assert seen["model"] == "deepseek-x"

    await client.generate_structured("sys", "usr", _Out)  # 不传 → 回退 primary
    assert seen["model"] == "claude-primary"
