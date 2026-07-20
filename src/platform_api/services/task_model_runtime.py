"""模型任务在每次执行开始时读取当前有效配置的共享入口。"""

from sqlalchemy.ext.asyncio import AsyncSession

from src.platform_api.core.model_runtime import ModelConfigBundle
from src.platform_api.services.model_settings_service import ModelSettingsService


async def load_active_model_bundle(session: AsyncSession) -> ModelConfigBundle:
    """读取本次执行要使用的最新版本；调用方随后用运行期作用域固定它。"""

    return await ModelSettingsService(session).load_active_bundle()
