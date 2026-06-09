"""T017: Playwright MCP 原型探索（可选，仅在 prototype_links 存在时触发）

注意：原型观察结果 trust_level=5（最低），仅辅助参考。
如果 Playwright 不可用或超时，静默跳过不影响主流程。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from src.testcase_generator.schemas.parsed_context import PrototypeObservation

logger = logging.getLogger(__name__)

# Playwright 探索超时（秒）
_FETCH_TIMEOUT = 30


@dataclass
class PlaywrightConfig:
    """Playwright MCP 连接配置"""

    endpoint: str = ""
    timeout: int = _FETCH_TIMEOUT
    enabled: bool = False


async def fetch_prototype_observations(
    prototype_links: list[str],
    config: PlaywrightConfig | None = None,
) -> list[PrototypeObservation]:
    """通过 Playwright MCP 探索可交互原型，返回观察记录

    Args:
        prototype_links: 原型 URL 列表
        config: Playwright 配置（不传或 enabled=False 则跳过）

    Returns:
        PrototypeObservation 列表；失败时返回空列表（静默降级）
    """
    if not prototype_links:
        return []

    if config is None or not config.enabled:
        logger.info("Playwright MCP 未启用，跳过原型探索")
        return []

    observations: list[PrototypeObservation] = []

    for link in prototype_links:
        try:
            obs = await asyncio.wait_for(
                _explore_single_prototype(link, config),
                timeout=config.timeout,
            )
            if obs:
                observations.append(obs)
        except asyncio.TimeoutError:
            logger.warning("Playwright 探索超时: %s", link)
        except Exception:
            logger.warning("Playwright 探索失败: %s", link, exc_info=True)

    return observations


async def _explore_single_prototype(
    url: str,
    config: PlaywrightConfig,
) -> PrototypeObservation | None:
    """探索单个原型页面（占位实现）

    实际实现需对接 Playwright MCP server。
    当前返回 None 作为占位，不阻塞主流程。
    """
    # TODO: 对接 Playwright MCP server
    # 1. 通过 MCP 发送导航指令
    # 2. 截图并识别页面元素
    # 3. 执行基本交互探索
    # 4. 返回观察结果
    logger.debug("Playwright 原型探索占位: %s", url)
    return None
