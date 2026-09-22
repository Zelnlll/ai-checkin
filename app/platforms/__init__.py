"""平台注册表：新增平台 = 新增一个模块 + 在此 import 一行。"""

from __future__ import annotations

from app.platforms.base import Adapter, CheckinResult

ADAPTERS: dict[str, Adapter] = {}


def register(adapter: Adapter) -> None:
    ADAPTERS[adapter.platform] = adapter


def get_adapter(platform: str) -> Adapter:
    return ADAPTERS[platform]


# 各适配器任务落地后在此追加 import（显式、可 grep）：
# from app.platforms import wps_lingxi, baidu_dazi, minimax, qoder, modelscope  # noqa: E402,F401

__all__ = ['ADAPTERS', 'Adapter', 'CheckinResult', 'register', 'get_adapter']
