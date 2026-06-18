"""cheat sheet API schema。"""

from typing import Literal

from pydantic import BaseModel, Field

from src.platform_api.models.enums import CheatSheetType


class CheatSheetEditRequest(BaseModel):
    """编辑 QA 版内容。"""

    qa_content: dict = Field(description="QA 修订后的内容")


class CheatSheetReviewRequest(BaseModel):
    """审核状态变更请求。"""

    status: Literal["approved", "rejected"] = Field(description="审核状态")
    comment: str | None = Field(default=None, description="拒绝原因/审核备注")
    by: str = Field(default="qa", description="审核人")


class CheatSheetBatchApproveRequest(BaseModel):
    """批量采纳请求。"""

    sheet_type: CheatSheetType = Field(description="条目类型")
    tier: str = Field(default="batch", description="审核档位")
    by: str = Field(default="qa", description="审核人")
