"""用例树 Service — 系统级用例树形聚合"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.repositories.batch_repo import BatchRepository
from src.platform_api.repositories.testcase_repo import TestCaseRepository
from src.testcase_generator.services.module_tree_classifier import classify_case_for_audit

CASE_TREE_VIEWS = {"all", "stable", "review_required"}


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
        bucket: str | None = None,
        verdict: str | None = None,
        review_issue_type: str | None = None,
        view: str | None = None,
        include_duplicates: bool = True,
    ) -> list[dict]:
        """
        获取系统级用例树

        返回结构:
        [{document_id, document_title, modules: [{module_name, case_count, cases: [...], branches: [...]}]}]
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

        view_mode = view or "all"
        if view_mode not in CASE_TREE_VIEWS:
            raise ValueError(f"unsupported case tree view: {view_mode}")

        effective_bucket = "main" if view_mode == "stable" and bucket is None else bucket
        effective_include_duplicates = False if view_mode == "stable" else include_duplicates
        exclude_review_required = view_mode == "stable"
        review_required_only = view_mode == "review_required"

        # 2. 查询用例数据
        cases_data = await self.testcase_repo.query_tree_data(
            batch_ids,
            priority,
            review_status,
            effective_bucket,
            verdict,
            include_duplicates=effective_include_duplicates,
        )

        # 3. 内存分组：Document → Business Module → Branch → Cases
        return self._assemble_tree(
            cases_data,
            review_issue_type=review_issue_type,
            exclude_review_required=exclude_review_required,
            review_required_only=review_required_only,
        )

    def _assemble_tree(
        self,
        cases_data: list[dict],
        *,
        review_issue_type: str | None = None,
        exclude_review_required: bool = False,
        review_required_only: bool = False,
    ) -> list[dict]:
        """
        内存分组逻辑：按 document → business_module → branch_path → case 层级聚合

        新批次用业务模块分类器派生资产组织坐标；旧批次无法识别时回退 source_section。
        """
        # doc_id → {document_id, document_title, modules_map: {module_name → module_data}}
        doc_map: dict[str, dict] = {}

        for case in cases_data:
            case_review_issue_type = self._review_issue_type_of(case)
            if review_issue_type and case_review_issue_type != review_issue_type:
                continue

            module_name, branch_path, classification = self._classify_tree_coordinates(case)
            is_review_required_queue = module_name == "待分类"
            if exclude_review_required and is_review_required_queue:
                continue
            if review_required_only and not is_review_required_queue:
                continue

            doc_id = str(case["document_id"])

            if doc_id not in doc_map:
                doc_map[doc_id] = {
                    "document_id": case["document_id"],
                    "document_title": case["document_title"],
                    "modules_map": {},
                }

            case_payload = {
                "id": case["id"],
                "title": case["title"],
                "priority": case["priority"],
                "trust_level": case["trust_level"],
                "review_status": case["review_status"],
                "iteration": case["iteration"],
                "verdict": case.get("verdict"),
                "bucket": case.get("bucket"),
                "review_issue_type": case_review_issue_type,
                "duplicate_of": case.get("duplicate_of"),
                "is_duplicate": case.get("duplicate_of") is not None,
                "branch_path": branch_path,
                "source_refs": classification.get("source_refs", []),
                "classification_confidence": classification.get("classification_confidence", "fallback"),
            }

            modules_map = doc_map[doc_id]["modules_map"]
            if module_name not in modules_map:
                modules_map[module_name] = {
                    "module_name": module_name,
                    "cases": [],
                    "branches_map": {},
                }

            module_data = modules_map[module_name]
            module_data["cases"].append(case_payload)
            branch_key = tuple(branch_path)
            module_data["branches_map"].setdefault(branch_key, []).append(case_payload)

        # 转换为最终树结构
        tree = []
        for doc_data in doc_map.values():
            modules = []
            for module_name, module_data in sorted(
                doc_data["modules_map"].items(),
                key=lambda item: (-len(item[1]["cases"]), item[0]),
            ):
                branches = [
                    {
                        "branch_name": " / ".join(branch_path),
                        "branch_path": list(branch_path),
                        "case_count": len(cases),
                        "cases": cases,
                    }
                    for branch_path, cases in sorted(
                        module_data["branches_map"].items(),
                        key=lambda item: (-len(item[1]), item[0]),
                    )
                ]
                modules.append(
                    {
                        "module_name": module_name,
                        "case_count": len(module_data["cases"]),
                        "cases": module_data["cases"],
                        "branches": branches,
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

    def _review_issue_type_of(self, case: dict) -> str | None:
        """从 verify JSON 中读取审查诊断类型；兼容未来可能的独立列。"""
        direct_value = case.get("review_issue_type")
        if direct_value:
            return str(direct_value)

        verification = case.get("verification") or {}
        if isinstance(verification, dict):
            value = verification.get("review_issue_type")
            if value:
                return str(value)
        return None

    def _classify_tree_coordinates(self, case: dict) -> tuple[str, list[str], dict]:
        """派生平台用例树坐标；旧批次无法识别时保留 source_section 兼容行为。"""
        provenance = case.get("provenance") or {}
        classification = classify_case_for_audit(
            {
                "title": case.get("title") or "",
                "provenance": provenance,
            }
        )
        module_name = classification.get("business_module") or "_review_required"
        branch_path = classification.get("branch_path") or ["通用规则"]

        source_section = str(provenance.get("source_section") or "").strip()
        if module_name == "_review_required":
            if source_section and source_section != "unresolved":
                return (
                    source_section,
                    [source_section],
                    {
                        **classification,
                        "classification_confidence": "legacy_source_section_fallback",
                    },
                )
            if not source_section:
                return (
                    "未分类",
                    ["未分类"],
                    {
                        **classification,
                        "classification_confidence": "legacy_uncategorized_fallback",
                    },
                )
            return "待分类", ["未匹配模块"], classification

        return str(module_name), [str(part) for part in branch_path], classification
