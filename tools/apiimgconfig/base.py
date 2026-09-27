"""云端生图 API 的公共配置结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ApiProtocol = Literal["direct_url", "async_task"]


@dataclass(frozen=True)
class CloudImageApiConfig:
    """描述一个云端模型的地址、调用协议、尺寸和默认参数。"""

    key: str
    display_name: str
    model: str
    endpoint: str
    protocol: ApiProtocol
    image_sizes: dict[str, tuple[int, int]]
    prompt_system_file: str
    prompt_guide_file: str | None = None
    supports_negative_prompt: bool = False
    request_defaults: dict[str, Any] = field(default_factory=dict)
    result_endpoint: str = ""
