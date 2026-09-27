"""Flux-2-Klein-9b API 配置。"""

from .base import CloudImageApiConfig


FLUX_CONFIG = CloudImageApiConfig(
    key="flux",
    display_name="Flux-2-Klein-9b",
    model="flux-2-klein-9b",
    endpoint="https://api.302.ai/flux/v1/flux-2-klein-9b",
    protocol="async_task",
    result_endpoint="https://api.302.ai/flux/v1/get_result",
    image_sizes={
        "character": (832, 1216),
        "scene": (1216, 832),
    },
    prompt_system_file="llm_system_prompt_api.txt",
    supports_negative_prompt=False,
    request_defaults={
        "steps": 40,
        # 提示词已经由 Prompt Optimizer 处理，避免二次扩写。
        "prompt_upsampling": False,
        "guidance": 2.5,
        "safety_tolerance": 2,
        "output_format": "jpeg",
        "sync": False,
    },
)
