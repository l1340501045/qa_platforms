"""导出 Celery 任务 — 查询已归档用例并生成 Markdown 或 Excel 文件上传至 MinIO"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update

from src.platform_api.core.celery_app import celery_app
from src.platform_api.core.minio_client import ensure_bucket_exists, minio_client
from src.platform_api.core.settings import settings
from src.platform_api.models.enums import BatchStatus, ReviewStatus
from src.platform_api.models.testcase import ExportTask, TestBatch, TestCase

logger = logging.getLogger(__name__)


@celery_app.task(name="platform_api.export", bind=True)
def export_task(
    self,
    export_id: str,
    scope: str,
    batch_id: str | None,
    system_id: str | None,
    format: str,
) -> dict:
    """
    导出任务执行流程：
    1. 查询已归档用例
    2. 生成 Markdown 或 Excel
    3. 上传 MinIO
    4. 更新 export_tasks.file_url + status=completed
    """
    import asyncio

    return asyncio.run(
        _execute_export(
            export_id=export_id,
            scope=scope,
            batch_id=batch_id,
            system_id=system_id,
            format=format,
        )
    )


async def _execute_export(
    export_id: str,
    scope: str,
    batch_id: str | None,
    system_id: str | None,
    format: str,
) -> dict:
    """内部异步执行逻辑"""
    from src.platform_api.core.database import get_session_factory

    session_factory = get_session_factory()

    try:
        async with session_factory() as session:
            # 1. 查询用例
            filters = []
            if scope == "batch" and batch_id:
                filters.append(TestCase.batch_id == UUID(batch_id))
            elif scope == "system" and system_id:
                # 查询系统下所有已归档批次的用例
                batch_ids_stmt = select(TestBatch.id).where(
                    TestBatch.system_id == UUID(system_id),
                    TestBatch.status == BatchStatus.ARCHIVED,
                )
                batch_ids_result = await session.execute(batch_ids_stmt)
                archived_batch_ids = [row[0] for row in batch_ids_result.fetchall()]
                if archived_batch_ids:
                    filters.append(TestCase.batch_id.in_(archived_batch_ids))
                else:
                    # 没有已归档批次，导出空文件
                    filters.append(TestCase.batch_id == UUID("00000000-0000-0000-0000-000000000000"))

            # 排除已删除的用例
            filters.append(TestCase.review_status != ReviewStatus.DELETED)

            stmt = select(TestCase).where(*filters).order_by(TestCase.created_at.asc())
            result = await session.execute(stmt)
            cases = list(result.scalars().all())

            # 2. 生成文件内容
            if format == "markdown":
                content, content_type, file_ext = _generate_markdown(cases), "text/markdown", "md"
            else:
                content, content_type, file_ext = (
                    _generate_excel(cases),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "xlsx",
                )

            # 3. 上传 MinIO
            ensure_bucket_exists()
            object_name = f"exports/{export_id}.{file_ext}"
            file_data = content if isinstance(content, bytes) else content.encode("utf-8")

            minio_client.put_object(
                bucket_name=settings.minio_bucket,
                object_name=object_name,
                data=io.BytesIO(file_data),
                length=len(file_data),
                content_type=content_type,
            )

            file_url = f"/{settings.minio_bucket}/{object_name}"

            # 4. 更新 export_tasks 记录
            update_stmt = (
                update(ExportTask)
                .where(ExportTask.id == UUID(export_id))
                .values(
                    status="completed",
                    file_url=file_url,
                    total_cases=len(cases),
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.execute(update_stmt)
            await session.commit()

        logger.info("Export %s completed: %d cases, format=%s", export_id, len(cases), format)
        return {"status": "completed", "export_id": export_id, "total_cases": len(cases)}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.exception("Export %s failed", export_id)

        # 更新失败状态
        async with session_factory() as session:
            update_stmt = (
                update(ExportTask)
                .where(ExportTask.id == UUID(export_id))
                .values(
                    status="failed",
                    error_message=error_msg,
                    completed_at=datetime.now(timezone.utc),
                )
            )
            await session.execute(update_stmt)
            await session.commit()

        return {"status": "failed", "export_id": export_id, "error": error_msg}


def _generate_markdown(cases: list) -> str:
    """将用例列表生成 Markdown 格式"""
    lines: list[str] = ["# 测试用例导出\n"]
    lines.append(f"导出时间: {datetime.now(timezone.utc).isoformat()}\n")
    lines.append(f"用例总数: {len(cases)}\n")
    lines.append("---\n")

    for i, case in enumerate(cases, 1):
        lines.append(f"## {i}. {case.title}\n")
        lines.append(f"**优先级**: {case.priority}\n")
        lines.append(f"**信任等级**: {case.trust_level}\n")

        # 前置条件
        lines.append("### 前置条件\n")
        preconditions = case.preconditions
        if isinstance(preconditions, list):
            for pc in preconditions:
                lines.append(f"- {pc}\n")
        elif isinstance(preconditions, dict):
            for k, v in preconditions.items():
                lines.append(f"- {k}: {v}\n")

        # 操作步骤
        lines.append("### 操作步骤\n")
        steps = case.steps
        if isinstance(steps, list):
            for j, step in enumerate(steps, 1):
                if isinstance(step, dict):
                    lines.append(f"{j}. {step.get('action', step)}\n")
                else:
                    lines.append(f"{j}. {step}\n")

        # 预期结果
        lines.append("### 预期结果\n")
        expected = case.expected_results
        if isinstance(expected, list):
            for er in expected:
                lines.append(f"- {er}\n")
        elif isinstance(expected, dict):
            for k, v in expected.items():
                lines.append(f"- {k}: {v}\n")

        lines.append("---\n")

    return "\n".join(lines)


def _generate_excel(cases: list) -> bytes:
    """将用例列表生成 Excel 格式（使用 openpyxl）"""
    try:
        from openpyxl import Workbook
    except ImportError:
        # 降级为 CSV
        return _generate_csv_fallback(cases)

    wb = Workbook()
    ws = wb.active
    ws.title = "测试用例"

    # 表头
    headers = ["序号", "标题", "优先级", "前置条件", "操作步骤", "预期结果", "信任等级", "维度"]
    ws.append(headers)

    for i, case in enumerate(cases, 1):
        preconditions = _format_field(case.preconditions)
        steps = _format_field(case.steps)
        expected = _format_field(case.expected_results)
        dimensions = _format_field(case.dimensions)

        ws.append([i, case.title, case.priority, preconditions, steps, expected, case.trust_level, dimensions])

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _generate_csv_fallback(cases: list) -> bytes:
    """降级 CSV 导出（openpyxl 不可用时）"""
    import csv

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["序号", "标题", "优先级", "前置条件", "操作步骤", "预期结果", "信任等级", "维度"])

    for i, case in enumerate(cases, 1):
        writer.writerow(
            [
                i,
                case.title,
                case.priority,
                _format_field(case.preconditions),
                _format_field(case.steps),
                _format_field(case.expected_results),
                case.trust_level,
                _format_field(case.dimensions),
            ]
        )

    return output.getvalue().encode("utf-8-sig")


def _format_field(value) -> str:
    """将 JSONB 字段格式化为可读字符串"""
    if isinstance(value, list):
        items = []
        for item in value:
            if isinstance(item, dict):
                items.append("; ".join(f"{k}={v}" for k, v in item.items()))
            else:
                items.append(str(item))
        return "\n".join(items)
    elif isinstance(value, dict):
        return "; ".join(f"{k}={v}" for k, v in value.items())
    return str(value) if value else ""
