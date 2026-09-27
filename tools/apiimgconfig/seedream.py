"""Seedream 5.0 Pro API 配置。"""

from .base import CloudImageApiConfig


SEEDREAM_CONFIG = CloudImageApiConfig(
    key="seedream",
    display_name="Seedream 5.0 Pro",
    model="doubao-seedream-5-0-pro-260628",
    endpoint="https://api.302ai.cn/doubao/images/generations",
    protocol="direct_url",
    image_sizes={
        "character": (1664, 2496),
        "scene": (2496, 1664),
    },
    prompt_system_file="llm_system_prompt_api.txt",
    supports_negative_prompt=False,
    request_defaults={
        "response_format": "url",
        "watermark": False,
    },
)
