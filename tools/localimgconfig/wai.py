"""WAI（Forge）模型配置。"""

from .base import LocalImageModelConfig


WAI_CONFIG = LocalImageModelConfig(
    key="wai",
    display_name="WAI NSFW Illustrious v15.0",
    protocol="forge",
    default_port=7860,
    txt2img_path="/sdapi/v1/txt2img",
    image_sizes={
        "character": (1024, 1400),
        "scene": (1400, 1024),
    },
    prompt_system_file="llm_system_prompt_local.txt",
    prompt_guide_file="WAI_Illustrious_v15_Public_Guide.md",
    supports_negative_prompt=True,
    supported_modes=("txt2img", "openpose"),
    checkpoint="waiNSFWIllustrious_v150.safetensors",
    request_defaults={
        "sampler_name": "Euler a",
        "scheduler": "automatic",
        "steps": 25,
        "cfg_scale": 6.0,
        "n_iter": 1,
        "batch_size": 1,
        "enable_hr": False,
        "send_images": True,
        "save_images": True,
    },
    reference_defaults={
        "controlnet_unit_count": 3,
        "module": "openpose_full",
        "model": "diffusion_pytorch_model [d0333a45]",
        "weight": 0.8,
        "guidance_start": 0.0,
        "guidance_end": 1.0,
        "control_mode": "Balanced",
        "resize_mode": "Crop and Resize",
        "pixel_perfect": True,
    },
)
