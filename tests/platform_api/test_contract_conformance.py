"""契约一致性测试 — 防止 API 表面与 contracts.md 再漂移

断言：
- 成功响应是 {code:0, message:"success", data:{...}}
- 分页 data 含 page/per_page/total_pages/items/total
- 错误响应是 {error_code, message, request_id}，error_code 在契约集合内
- current_stage / stages 用对外 canonical 阶段名（连字符版）
"""

import pytest
from httpx import AsyncClient, ASGITransport

from src.platform_api.main import app
from src.platform_api.core.exceptions import ERROR_CODES
from src.platform_api.core.stage_names import PIPELINE_STAGES


@pytest.fixture
async def client():
    """HTTPX async client for testing FastAPI app"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_success_response_envelope(client: AsyncClient):
    """成功响应必须是 {code:0, message:"success", data:{...}}"""
    resp = await client.get("/api/v1/systems", params={"page": 1, "per_page": 5})
    assert resp.status_code == 200
    body = resp.json()

    # 信封结构
    assert "code" in body, f"缺少 code 字段: {body.keys()}"
    assert body["code"] == 0, f"code 应为 0, got {body['code']}"
    assert body["message"] == "success"
    assert "data" in body, f"缺少 data 字段: {body.keys()}"


@pytest.mark.asyncio
async def test_paginated_response_format(client: AsyncClient):
    """分页 data 必须含 items/total/page/per_page/total_pages"""
    resp = await client.get("/api/v1/systems", params={"page": 1, "per_page": 10})
    assert resp.status_code == 200
    data = resp.json()["data"]

    required_fields = {"items", "total", "page", "per_page", "total_pages"}
    assert required_fields.issubset(set(data.keys())), (
        f"分页字段缺失: {required_fields - set(data.keys())}, got {data.keys()}"
    )
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)
    assert data["page"] >= 1
    assert data["per_page"] >= 1
    assert data["total_pages"] >= 0


@pytest.mark.asyncio
async def test_error_response_format(client: AsyncClient):
    """错误响应必须是 {error_code, message, request_id}，error_code 在契约集合内"""
    # 请求不存在的资源触发 404
    from uuid import uuid4

    resp = await client.get(f"/api/v1/systems/{uuid4()}")
    # 资源不存在必须是确定性的 404 + E4041，不接受 500（500 等于纵容未处理异常）
    assert resp.status_code == 404, f"不存在资源应返回 404, got {resp.status_code}"
    body = resp.json()

    # 错误信封结构
    assert "error_code" in body, f"错误响应缺少 error_code: {body.keys()}"
    assert "message" in body, f"错误响应缺少 message: {body.keys()}"
    assert "request_id" in body, f"错误响应缺少 request_id: {body.keys()}"

    # 资源不存在的确定性错误码
    assert body["error_code"] == "E4041", (
        f"不存在资源的 error_code 应为 E4041, got '{body['error_code']}'"
    )
    # 且必须在契约集合内
    assert body["error_code"] in ERROR_CODES


@pytest.mark.asyncio
async def test_stage_names_are_canonical(client: AsyncClient):
    """阶段名必须用对外 canonical 版本（连字符）"""
    from src.platform_api.core.stage_names import to_canonical

    # 验证映射函数输出只有 canonical 名
    internal_names = ["parse", "comprehend", "test_points", "write_cases", "review", "export"]
    for internal in internal_names:
        canonical = to_canonical(internal)
        assert "-" in canonical or canonical in ("parse", "comprehend", "gate", "export"), (
            f"'{internal}' 映射为 '{canonical}'，应含连字符或为保留单词"
        )

    # 验证 PIPELINE_STAGES 全是 canonical
    for stage in PIPELINE_STAGES:
        assert "_" not in stage, f"PIPELINE_STAGES 含下划线: '{stage}'"
