"""用例树 Service — 系统级用例树形聚合"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.repositories.batch_repo import BatchRepository
from src.platform_api.repositories.testcase_repo import TestCaseRepository


class CaseTreeService:
    """用例树聚合逻辑"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.batch_repo = BatchRepository(session)
        self.testcase_repo = TestCaseRepository(session)

    async def get_case_tree(
        self,
        system_id: UUID,
        batch_id: UUID | None = None,
        priority: str | None = None,
        review_status: str | None = None,
    ) -> list[dict]:
        """
        获取系统级用例树

        返回结构: [{document_id, document_title, modules: [{module_name, case_count, cases: [...]}]}]
        """
        # 1. 确定批次范围
        if batch_id:
            batch_ids = [batch_id]
        else:
            # 取各文档最新可见批次（pending_review/completed/archived）
            latest_batches = await self.batch_repo.find_latest_viewable_per_document(system_id)
            batch_ids = [b["id"] for b in latest_batches]

        if not batch_ids:
            return []

        # 2. 查询用例数据
        cases_data = await self.testcase_repo.query_tree_data(batch_ids, priority, review_status)

        # 3. 内存分组：Document → Module(source_section) → Cases
        return self._assemble_tree(cases_data)

    def _assemble_tree(self, cases_data: list[dict]) -> list[dict]:
        """
        内存分组逻辑：按 document → module(source_section) → case 层级聚合

        module_name 取自 provenance->source_section
        """
        # doc_id → {document_id, document_title, modules_map: {module_name → [cases]}}
        doc_map: dict[str, dict] = {}

        for case in cases_data:
            doc_id = str(case["document_id"])

            if doc_id not in doc_map:
                doc_map[doc_id] = {
                    "document_id": case["document_id"],
                    "document_title": case["document_title"],
                    "modules_map": {},
                }

            # 提取 module_name
            provenance = case.get("provenance") or {}
            module_name = provenance.get("source_section", "未分类")

            modules_map = doc_map[doc_id]["modules_map"]
            if module_name not in modules_map:
                modules_map[module_name] = []

            modules_map[module_name].append(
                {
                    "id": case["id"],
                    "title": case["title"],
                    "priority": case["priority"],
                    "trust_level": case["trust_level"],
                    "review_status": case["review_status"],
                    "iteration": case["iteration"],
                }
            )

        # 转换为最终树结构
        tree = []
        for doc_data in doc_map.values():
            modules = []
            for module_name, cases in doc_data["modules_map"].items():
                modules.append(
                    {
                        "module_name": module_name,
                        "case_count": len(cases),
                        "cases": cases,
                    }
                )
            tree.append(
                {
                    "document_id": doc_data["document_id"],
                    "document_title": doc_data["document_title"],
                    "modules": modules,
                }
            )

        return tree
