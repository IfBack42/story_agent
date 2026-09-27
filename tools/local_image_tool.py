"""统一的本地/自建服务器生图工具。

一句话模型：
    model_name 决定“找哪张模型配置表”，port 决定“从哪个门进去”，
    mode 决定“纯文字生成，还是先收一张参考图再生成”。

模型参数统一注册在 tools/localimgconfig/：
    wai              -> Forge 原生 API；参考图模式是 OpenPose
    qwen_image_2_1   -> 千问原生 API；支持 txt2img / img2img
"""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import requests

from .localimgconfig import (
    DEFAULT_LOCAL_IMAGE_MODEL,
    GenerationMode,
    LocalImageModelConfig,
    get_local_image_config,
)

try:
    from langchain_core.tools import tool
except ImportError:  # pragma: no cover - 方便脱离 LangChain 单独调试
    def tool(*decorator_args, **_decorator_kwargs):  # type: ignore[misc]
        if decorator_args and callable(decorator_args[0]):
            return decorator_args[0]

        def decorate(func):
            return func

        return decorate


BASE_DIR = Path(__file__).resolve().parent.parent
PICTURES_DIR = BASE_DIR / "pictures"
REQUEST_TIMEOUT = (15, 900)


class LocalImageError(RuntimeError):
    """本地或自建服务器生图失败。"""


def _safe_file_stem(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("._")
    return cleaned or "illustration"


def _read_image_as_base64(image_path: str | Path) -> str:
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise LocalImageError(f"参考图不存在：{path}")
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        raise LocalImageError(f"不支持的参考图格式：{path.suffix}")
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _read_image_as_data_url(image_path: str | Path) -> str:
    path = Path(image_path).expanduser()
    encoded = _read_image_as_base64(path)
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime_type};base64,{encoded}"


def _save_images(
    images_base64: list[str],
    seeds: list[int],
    output_prefix: str,
    output_dir: Path = PICTURES_DIR,
) -> list[Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = f"{datetime.now():%Y%m%d_%H%M%S}"
    prefix = _safe_file_stem(output_prefix)
    paths: list[Path] = []

    for index, encoded in enumerate(images_base64):
        if encoded.startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        seed = seeds[index] if index < len(seeds) else "unknown"
        path = output_dir / f"{prefix}_{timestamp}_{seed}.png"
        if path.exists():
            path = output_dir / f"{prefix}_{timestamp}_{seed}_{index}.png"
        try:
            path.write_bytes(base64.b64decode(encoded))
        except (ValueError, TypeError) as error:
            raise LocalImageError("服务返回了无法解码的图片数据。") from error
        paths.append(path)
    return paths


def _build_openpose_units(
    config: LocalImageModelConfig,
    reference_image_path: str,
) -> list[dict[str, Any]]:
    defaults = config.reference_defaults
    unit = {
        "enabled": True,
        "image": _read_image_as_base64(reference_image_path),
        "module": defaults["module"],
        "model": defaults["model"],
        "weight": defaults["weight"],
        "guidance_start": defaults["guidance_start"],
        "guidance_end": defaults["guidance_end"],
        "control_mode": defaults["control_mode"],
        "resize_mode": defaults["resize_mode"],
        "pixel_perfect": defaults["pixel_perfect"],
        "processor_res": -1,
        "threshold_a": -1,
        "threshold_b": -1,
        "save_detected_map": False,
    }
    count = int(defaults.get("controlnet_unit_count", 1))
    return [unit, *({"enabled": False} for _ in range(max(0, count - 1)))]


def _build_forge_payload(
    config: LocalImageModelConfig,
    *,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    mode: GenerationMode,
    reference_image_path: str | None,
) -> dict[str, Any]:
    payload = dict(config.request_defaults)
    payload.update(
        {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "seed": seed,
        }
    )
    if config.checkpoint:
        payload["sd_model_checkpoint"] = config.checkpoint

    if mode == "openpose":
        if not reference_image_path:
            raise LocalImageError("OpenPose 模式必须提供参考图位置。")
        payload["alwayson_scripts"] = {
            "ControlNet": {
                "args": _build_openpose_units(config, reference_image_path)
            }
        }
    return payload


def _build_qwen_payload(
    config: LocalImageModelConfig,
    *,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    seed: int,
    mode: GenerationMode,
    reference_image_path: str | None,
) -> dict[str, Any]:
    payload = dict(config.request_defaults)
    payload.update(
        {
            "prompt": prompt,
            "negative_prompt": negative_prompt,
            "width": width,
            "height": height,
            "seed": seed,
        }
    )
    if mode == "img2img":
        if not reference_image_path:
            raise LocalImageError("千问 img2img 模式必须提供参考图位置。")
        # 本机路径对远程服务器不可见，因此读取后作为 data URL 放进 JSON。
        payload["image"] = _read_image_as_data_url(reference_image_path)
    return payload


def _parse_response(
    config: LocalImageModelConfig,
    response_data: dict[str, Any],
) -> tuple[list[str], list[int]]:
    images = response_data.get("images") or []
    if not isinstance(images, list) or not images:
        raise LocalImageError(f"{config.display_name} 没有返回图片。")

    if config.protocol == "forge":
        raw_info = response_data.get("info") or "{}"
        try:
            info = json.loads(raw_info) if isinstance(raw_info, str) else raw_info
        except ValueError:
            info = {}
        seeds = list((info or {}).get("all_seeds") or [])
    else:
        seeds = list(response_data.get("seeds") or [])
    return images, seeds


def ask_reference_image_path(mode: GenerationMode) -> str:
    """在每次实际生成前询问这一次要用的参考图。"""

    purpose = "OpenPose 姿势参考图" if mode == "openpose" else "千问 img2img 参考图"
    while True:
        value = input(f"请输入本次{purpose}的本机路径：\n> ").strip().strip('"')
        path = Path(value).expanduser()
        if path.is_file():
            return str(path.resolve())
        print(f"参考图不存在：{path}，请重新输入。", flush=True)


def generate_local_image(
    *,
    prompt: str,
    image_type: Literal["character", "scene"],
    model_name: str = DEFAULT_LOCAL_IMAGE_MODEL,
    port: int | None = None,
    mode: GenerationMode = "txt2img",
    negative_prompt: str = "",
    seed: int = -1,
    reference_image_path: str | None = None,
    output_prefix: str = "illustration",
    output_dir: Path = PICTURES_DIR,
) -> dict[str, Any]:
    """根据注册配置调用指定模型，并把返回图片保存到 pictures/。"""

    if not prompt.strip():
        raise LocalImageError("prompt 不能为空。")

    try:
        config = get_local_image_config(model_name)
    except ValueError as error:
        raise LocalImageError(str(error)) from error

    if mode not in config.supported_modes:
        allowed = "、".join(config.supported_modes)
        raise LocalImageError(
            f"{config.display_name} 不支持 {mode}；可用模式：{allowed}。"
        )
    try:
        width, height = config.image_sizes[image_type]
    except KeyError as error:
        allowed = "、".join(config.image_sizes)
        raise LocalImageError(f"image_type 只能填写 {allowed}。") from error

    actual_port = config.default_port if port is None else int(port)
    if not 1 <= actual_port <= 65535:
        raise LocalImageError(f"端口不合法：{actual_port}")

    common = {
        "config": config,
        "prompt": prompt.strip(),
        "negative_prompt": negative_prompt.strip(),
        "width": width,
        "height": height,
        "seed": seed,
        "mode": mode,
        "reference_image_path": reference_image_path,
    }
    if config.protocol == "forge":
        payload = _build_forge_payload(**common)
        endpoint = config.txt2img_path
    elif config.protocol == "qwen":
        payload = _build_qwen_payload(**common)
        endpoint = config.img2img_path if mode == "img2img" else config.txt2img_path
        if endpoint is None:
            raise LocalImageError(f"{config.display_name} 没有注册 img2img 接口。")
    else:  # pragma: no cover
        raise LocalImageError(f"未知协议：{config.protocol}")

    url = f"http://127.0.0.1:{actual_port}{endpoint}"
    started = time.time()
    try:
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as error:
        raise LocalImageError(
            f"连不上 {config.display_name}：{url}。请确认服务已启动；"
            "远程服务器还要先建立 SSH 端口转发。"
        ) from error
    except requests.exceptions.HTTPError as error:
        detail = getattr(error.response, "text", "")
        raise LocalImageError(
            f"{config.display_name} 返回 HTTP "
            f"{getattr(error.response, 'status_code', '?')}：{detail[:800]}"
        ) from error
    except requests.exceptions.RequestException as error:
        raise LocalImageError(f"请求 {config.display_name} 失败：{error}") from error

    try:
        response_data = response.json()
    except ValueError as error:
        raise LocalImageError(f"服务返回的不是 JSON：{response.text[:500]}") from error

    images, seeds = _parse_response(config, response_data)
    paths = _save_images(images, seeds, output_prefix, output_dir)
    return {
        "paths": [str(path) for path in paths],
        "seeds": seeds,
        "elapsed_seconds": round(time.time() - started, 1),
        "size": f"{width}x{height}",
        "model": config.display_name,
        "mode": mode,
        "port": actual_port,
        "used_reference_image": reference_image_path is not None,
    }


def _format_result(result: dict[str, Any]) -> str:
    return (
        f"插画已生成并保存到：{'；'.join(result['paths'])}\n"
        f"模型={result['model']}，模式={result['mode']}，端口={result['port']}，"
        f"seed={result['seeds'] or ['未知']}，尺寸={result['size']}，"
        f"耗时={result['elapsed_seconds']} 秒，"
        f"参考图={'已使用' if result['used_reference_image'] else '未使用'}。"
    )


@tool
def draw_illustration_local(
    prompt: str,
    image_type: Literal["character", "scene"],
    model_name: str = DEFAULT_LOCAL_IMAGE_MODEL,
    port: int = 0,
    mode: GenerationMode = "txt2img",
    negative_prompt: str = "",
    seed: int = -1,
    reference_image_path: str = "",
    output_prefix: str = "illustration",
) -> str:
    """调用已注册的本地或自建服务器模型生成插画。

    model_name 选择模型；port=0 使用该模型注册的默认端口。
    Qwen 的 mode 可选 txt2img 或 img2img；WAI 可选 txt2img 或 openpose。
    参考图模式下，reference_image_path 必须是本机图片路径。
    """

    try:
        result = generate_local_image(
            prompt=prompt,
            image_type=image_type,
            model_name=model_name,
            port=port or None,
            mode=mode,
            negative_prompt=negative_prompt,
            seed=seed,
            reference_image_path=reference_image_path.strip() or None,
            output_prefix=output_prefix,
        )
    except LocalImageError as error:
        return f"画图失败：{error}"
    return _format_result(result)


def build_local_image_tool(
    model_name: str = DEFAULT_LOCAL_IMAGE_MODEL,
    port: int | None = None,
    mode: GenerationMode = "txt2img",
    output_dir: Path = PICTURES_DIR,
):
    """把模型、端口和模式绑定成一个给 Agent 使用的 Tool。

    当模式需要参考图时，每次 Tool 真正执行前都会重新询问路径。
    """

    config = get_local_image_config(model_name)
    if mode not in config.supported_modes:
        allowed = "、".join(config.supported_modes)
        raise ValueError(f"{config.display_name} 不支持 {mode}；可用模式：{allowed}。")

    @tool("draw_illustration_local")
    def configured_local_image_tool(
        prompt: str,
        image_type: Literal["character", "scene"],
        negative_prompt: str = "",
        seed: int = -1,
        output_prefix: str = "illustration",
    ) -> str:
        """使用程序预先选定的本地生图模型生成一张插画。

        image_type 只能是 character（人物竖图）或 scene（场景横图）。
        调用前应先使用提示词优化工具；一次调用只生成一次，避免重复消耗时间。
        """

        reference_path = ask_reference_image_path(mode) if mode != "txt2img" else None
        try:
            result = generate_local_image(
                prompt=prompt,
                image_type=image_type,
                model_name=model_name,
                port=port,
                mode=mode,
                negative_prompt=negative_prompt,
                seed=seed,
                reference_image_path=reference_path,
                output_prefix=output_prefix,
                output_dir=output_dir,
            )
        except LocalImageError as error:
            return f"画图失败：{error}"
        return _format_result(result)

    return configured_local_image_tool


if __name__ == "__main__":
    # 直接改这三项即可测试不同模型。参考图模式会在运行时询问图片位置。
    TEST_MODEL = "wai"
    TEST_PORT: int | None = 16006
    TEST_MODE: GenerationMode = "txt2img"

    result = generate_local_image(
        prompt="1girl, reading a book, cozy library, warm light, anime illustration",
        image_type="character",
        model_name=TEST_MODEL,
        port=TEST_PORT,
        mode=TEST_MODE,
        reference_image_path=(
            ask_reference_image_path(TEST_MODE) if TEST_MODE != "txt2img" else None
        ),
        output_prefix="tool_selftest",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
