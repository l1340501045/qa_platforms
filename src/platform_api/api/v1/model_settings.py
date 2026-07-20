"""全平台 AI 模型设置 API。"""

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.database import get_session
from src.platform_api.core.exceptions import ApiError
from src.platform_api.core.model_runtime import ModelRole
from src.platform_api.core.response import success
from src.platform_api.schemas.model_settings import ModelConnectionRequest, SaveModelSettingRequest
from src.platform_api.services.model_settings_service import ModelSettingsService


def _require_same_origin(request: Request) -> None:
    """阻止外部网页借用户浏览器调用无鉴权的内网设置接口。"""

    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlsplit(origin)
    request_host = request.headers.get("host", "")
    if parsed.scheme in {"http", "https"} and parsed.netloc.casefold() == request_host.casefold():
        return
    raise ApiError("E4031", "模型设置接口只允许从当前平台页面访问")


router = APIRouter(
    prefix="/settings/ai-models",
    tags=["AI 模型设置"],
    dependencies=[Depends(_require_same_origin)],
)


def _get_service(session: AsyncSession = Depends(get_session, scope="function")) -> ModelSettingsService:
    return ModelSettingsService(session)


@router.get("")
async def get_ai_model_settings(service: ModelSettingsService = Depends(_get_service)):
    """读取四类模型的当前脱敏配置。"""

    return success(await service.get_settings())


@router.post("/{role}/test")
async def test_ai_model_connection(
    role: ModelRole,
    data: ModelConnectionRequest,
    service: ModelSettingsService = Depends(_get_service),
):
    """真实测试单类模型连接，但不保存。"""

    return success(await service.test_model(role, data))


@router.put("/{role}")
async def save_ai_model_setting(
    role: ModelRole,
    data: SaveModelSettingRequest,
    service: ModelSettingsService = Depends(_get_service),
):
    """服务端复测成功后保存并启用单类模型。"""

    return success(await service.save_model(role, data))
