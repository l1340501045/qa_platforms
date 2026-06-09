"""KB 配置 — 复用 platform_api 全局配置，不重新定义"""

from src.platform_api.core.settings import settings

# 直接引用，供模块内使用
kb_settings = settings
