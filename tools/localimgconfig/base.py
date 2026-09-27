"""本地/自建服务器生图模型的公共配置结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


LocalImageProtocol = Literal["forge", "qwen"]
GenerationMode = Literal["txt2img", "img2img", "openpose"]


@dataclass(frozen=True)
class LocalImageModelConfig:
    """描述一个模型如何连接、支持哪些模式，以及各自的默认参数。"""

    key: str
    display_name: str
    protocol: LocalImageProtocol
    default_port: int
    txt2img_path: str
    image_sizes: dict[str, tuple[int, int]]
    prompt_system_file: str
    prompt_guide_file: str | None = None
    supports_negative_prompt: bool = False
    supported_modes: tuple[GenerationMode, ...] = ("txt2img",)
    img2img_path: str | None = None
    checkpoint: str | None = None
    request_defaults: dict[str, Any] = field(default_factory=dict)
    reference_defaults: dict[str, Any] = field(default_factory=dict)

    @property
    def supports_reference_image(self) -> bool:
        """是否有任意一种需要参考图的生成模式。"""

        return "img2img" in self.supported_modes or "openpose" in self.supported_modes
