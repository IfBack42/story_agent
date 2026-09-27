"""本地与自建服务器生图模型注册表。

新增模型时：
1. 新建一个模型配置文件；
2. 在 ``LOCAL_IMAGE_MODELS`` 中注册；
3. 如果它使用新协议，再在 local_image_tool.py 增加对应请求适配器。
"""

from __future__ import annotations

from .base import GenerationMode, LocalImageModelConfig, LocalImageProtocol
from .qwen_image_2_1 import QWEN_IMAGE_2_1_CONFIG
from .wai import WAI_CONFIG


LOCAL_IMAGE_MODELS: dict[str, LocalImageModelConfig] = {
    WAI_CONFIG.key: WAI_CONFIG,
    QWEN_IMAGE_2_1_CONFIG.key: QWEN_IMAGE_2_1_CONFIG,
}

DEFAULT_LOCAL_IMAGE_MODEL = "wai"


def get_local_image_config(model_name: str) -> LocalImageModelConfig:
    """按短名称获取模型配置，并给出可读的错误信息。"""

    normalized = model_name.strip().lower()
    try:
        return LOCAL_IMAGE_MODELS[normalized]
    except KeyError as error:
        allowed = "、".join(LOCAL_IMAGE_MODELS)
        raise ValueError(
            f"不支持的本地模型：{model_name}；只能填写 {allowed}。"
        ) from error


__all__ = [
    "DEFAULT_LOCAL_IMAGE_MODEL",
    "GenerationMode",
    "LOCAL_IMAGE_MODELS",
    "LocalImageModelConfig",
    "LocalImageProtocol",
    "get_local_image_config",
]
