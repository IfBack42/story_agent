"""Qwen-Image-2.1 自建 API 服务配置。"""

from .base import LocalImageModelConfig


QWEN_IMAGE_2_1_CONFIG = LocalImageModelConfig(
    key="qwen_image_2_1",
    display_name="Qwen-Image-2.1",
    protocol="qwen",
    default_port=6006,
    txt2img_path="/txt2img",
    img2img_path="/img2img",
    image_sizes={
        # Qwen-Image-2.1 的长宽必须是 16 的倍数。
        "character": (1024, 1408),
        "scene": (1408, 1024),
    },
    prompt_system_file="llm_system_prompt_local.txt",
    prompt_guide_file="Qwen_Image_Prompt_Guide.md",
    supports_negative_prompt=True,
    supported_modes=("txt2img", "img2img"),
    request_defaults={
        "num_inference_steps": 30,
        # Qwen-Image-2.1 只有在 true_cfg_scale > 1 时才会使用 negative_prompt。
        "true_cfg_scale": 2.0,
        "num_images": 1,
        "use_kv_cache": True,
    },
)
