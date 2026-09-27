"""云端生图 API 注册表。

新增云端模型时：
1. 为它新建一个独立配置文件；
2. 在 ``CLOUD_IMAGE_APIS`` 中注册；
3. 只有出现新调用协议时，才需要修改 api_image_tool.py。
"""

from __future__ import annotations

from .base import ApiProtocol, CloudImageApiConfig
from .flux import FLUX_CONFIG
from .seedream import SEEDREAM_CONFIG


CLOUD_IMAGE_APIS: dict[str, CloudImageApiConfig] = {
    SEEDREAM_CONFIG.key: SEEDREAM_CONFIG,
    FLUX_CONFIG.key: FLUX_CONFIG,
}

DEFAULT_CLOUD_IMAGE_API = "seedream"


def get_cloud_api_config(api_model: str) -> CloudImageApiConfig:
    """按短名称取得配置，并对无效名称给出可读错误。"""

    normalized = api_model.strip().lower()
    try:
        return CLOUD_IMAGE_APIS[normalized]
    except KeyError as error:
        allowed = "、".join(CLOUD_IMAGE_APIS)
        raise ValueError(
            f"不支持的 api_model：{api_model}；只能填写 {allowed}。"
        ) from error


__all__ = [
    "ApiProtocol",
    "CLOUD_IMAGE_APIS",
    "CloudImageApiConfig",
    "DEFAULT_CLOUD_IMAGE_API",
    "FLUX_CONFIG",
    "SEEDREAM_CONFIG",
    "get_cloud_api_config",
]
