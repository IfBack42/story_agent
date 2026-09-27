"""
API 图像生成工具（Tool 第 2 号 · 云端接口版）
=============================================

它做的事情，用一句话说清楚：
    把一段文字提示词，交给 apiimgconfig/ 中注册的云端图像模型，
    然后拿回一张图片存到 story_agent/pictures/。

为什么要有这个版本：
    本地 Forge 需要独立显卡，别人拿到你的项目跑不起来；
    云端版只要有网络 + 一个 API Key 就能出图。

和本地版（local_image_tool.py）的分工：
    ┌─────────────┬──────────────────────┬──────────────────────────┐
    │             │ draw_illustration_   │ draw_illustration_       │
    │             │ local（本地 Forge）  │ cloud（本文件·云端）     │
    ├─────────────┼──────────────────────┼──────────────────────────┤
    │ 硬件要求    │ 需要显卡 + Forge     │ 只要联网                 │
    │ 花钱        │ 电费                 │ 按张计费                 │
    │ 速度        │ 85~135 秒            │ 20~90 秒（首次实测 75 秒）│
    │ 负面提示词  │ 支持                 │ 不支持（写进 prompt 里） │
    │ ControlNet  │ 支持（姿势参考图）   │ 不支持                   │
    │ 内容审核    │ 无                   │ 有，可能被拦截           │
    │ 出图风格    │ 由你本地的模型决定   │ 由云端模型决定           │
    │ 复现性      │ 给 seed 可精确复现   │ 不回传 seed，复现较弱    │
    └─────────────┴──────────────────────┴──────────────────────────┘

两个工具返回的"结果说明"字典用的是同一套核心字段，
所以以后上层 Agent 想换后端，基本不用改代码：
    paths（图片路径列表）/ seeds / elapsed_seconds / size

数据流：
    Seedream：提示词 -> POST -> 图片 URL -> 下载并保存
    Flux：提示词 -> POST 提交任务 -> 轮询任务 -> 图片 URL -> 下载并保存
    （临时网址有时效，所以要立刻下载，不能只把网址记下来）

API Key 从哪来（按优先级）：
    1. 系统环境变量 AI_302_API_KEY（你这台机器已经设好了，最省事）
    2. 也可以在 story_agent/ 下建一个 .env 文件，写：AI_302_API_KEY=你的key
    Key 不要写进代码里，更不要提交到公开仓库。

最常见的坑：内容审核
    豆包模型自带内容审核。如果提示词涉及敏感内容，接口不会报"网络错误"，
    而是直接告诉你生成被拦截（错误码里带 SensitiveContent）。
    遇到这种情况改提示词即可，本工具会把这句提示原样告诉你。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import requests

try:  # 有 langchain 时用真正的 @tool；没有时退化成普通函数，方便单独调试。
    from langchain_core.tools import tool
except ImportError:  # pragma: no cover - 仅用于缺少 langchain 的环境
    def tool(func):  # type: ignore[misc]
        return func

try:
    from tools.apiimgconfig import (
        CLOUD_IMAGE_APIS,
        DEFAULT_CLOUD_IMAGE_API,
        SEEDREAM_CONFIG,
        get_cloud_api_config,
    )
except ModuleNotFoundError:  # 允许直接运行 tools/api_image_tool.py
    from apiimgconfig import (  # type: ignore[no-redef]
        CLOUD_IMAGE_APIS,
        DEFAULT_CLOUD_IMAGE_API,
        SEEDREAM_CONFIG,
        get_cloud_api_config,
    )


# ---------------------------------------------------------------------------
# 一、路径（基本不用动）
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent      # -> story_agent/
PICTURES_DIR = BASE_DIR / "pictures"                   # 生成结果统一放这里
ENV_FILE = BASE_DIR / ".env"                           # 可选：放 API Key 的地方


class ApiImageError(RuntimeError):
    """本工具自己抛的错误，方便上层区分"接口出问题"还是"代码写错了"。"""


# ---------------------------------------------------------------------------
# 二、参数定义：分成"连接类"和"请求类"两堆
# ---------------------------------------------------------------------------
#
# 为什么分两堆：
#     ApiImageSettings = 换平台、换 Key 名、换保存目录时才动的东西（配置）
#     ApiImageParams   = 每次出图可能都不一样的东西（模型、尺寸、种子）
#
# 想临时改其中一两个字段，不用重写整个对象，用 dataclasses.replace：
#     replace(DEFAULT_API_PARAMS, model="别的模型名")
# 它返回一个"改好字段的新对象"，不会污染默认值。


@dataclass
class ApiImageSettings:
    """连接类配置：接口地址、Key 从哪读、图片存哪、超时。"""

    endpoint: str = SEEDREAM_CONFIG.endpoint
    api_key_env_name: str = "AI_302_API_KEY"
    env_file: Path = ENV_FILE
    output_dir: Path = PICTURES_DIR
    request_timeout: tuple[int, int] = (20, 800)   # (连接超时, 读取超时)
    download_timeout: int = 120                    # 下载图片的超时


@dataclass
class ApiImageParams:
    """请求类参数：这次用哪个模型、多大、什么种子。

    注意：这个接口没有 negative_prompt 参数，
    不想要的元素要写进 prompt（而且要"用替代法，不用否定法"）。
    """

    model: str = SEEDREAM_CONFIG.model
    # 底层函数仍保留 size，Agent Tool 会按 image_type 在每次调用时覆盖。
    size: str = "x".join(map(str, SEEDREAM_CONFIG.image_sizes["character"]))
    watermark: bool = False     # 是否加平台水印，False = 不加
    seed: int = -1              # -1 = 随机；填具体数字尝试复现（云端不一定保证）


DEFAULT_API_SETTINGS = ApiImageSettings()
DEFAULT_API_PARAMS = ApiImageParams()


# ---------------------------------------------------------------------------
# 三、小工具函数
# ---------------------------------------------------------------------------


def _load_env_file(env_path: Path) -> None:
    """读一个 .env 文件，把里面的 KEY=VALUE 塞进环境变量。

    这里手写 6 行而不是装 python-dotenv，是为了少一个依赖；
    用 setdefault 的用意是：系统环境变量优先级最高，.env 只做兜底。
    """
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_api_key(settings: ApiImageSettings = DEFAULT_API_SETTINGS) -> str:
    """取出 API Key：先看系统环境变量，再看 settings.env_file 指定的 .env。"""
    _load_env_file(settings.env_file)
    api_key = os.environ.get(settings.api_key_env_name, "").strip()
    if not api_key:
        raise ApiImageError(
            f"没有找到 {settings.api_key_env_name}。两种办法二选一：\n"
            f"  1. 设置系统环境变量 {settings.api_key_env_name}=你的密钥\n"
            f"  2. 在 {settings.env_file} 里写一行："
            f"{settings.api_key_env_name}=你的密钥"
        )
    return api_key


def _parse_api_response(response: requests.Response) -> list[dict]:
    """把接口响应解析成字典列表。

    正常情况是一段标准 JSON；但部分兼容接口即使传了 stream=False，
    也会返回"连续多段 JSON"或者带 data: 前缀的 SSE 文本，
    所以这里留一条兜底路径，免得偶尔一次就被卡住。
    """
    try:
        result = response.json()
        return result if isinstance(result, list) else [result]
    except ValueError:
        decoder = json.JSONDecoder()
        text_parts: list[str] = []
        for line in response.text.splitlines():
            line = line.strip()
            if not line or line in {"[DONE]", "data: [DONE]"}:
                continue
            if line.startswith("data:"):
                line = line.removeprefix("data:").lstrip()
            text_parts.append(line)

        text = "\n".join(text_parts)
        documents: list[dict] = []
        position = 0
        try:
            while position < len(text):
                while position < len(text) and text[position].isspace():
                    position += 1
                if position >= len(text):
                    break
                document, position = decoder.raw_decode(text, position)
                documents.append(document)
        except (json.JSONDecodeError, ValueError) as error:
            raise ApiImageError(
                "接口返回的内容不是可识别的 JSON。"
                f"\nContent-Type: {response.headers.get('Content-Type', '未知')}"
                f"\n响应内容（前 500 字符）：{response.text[:500]}"
            ) from error

        if not documents:
            raise ApiImageError(f"接口返回空响应，HTTP 状态码：{response.status_code}")
        return documents


def _find_key_recursively(value: Any, key_name: str, *, url_only: bool = False) -> Any:
    """在嵌套的字典/列表里递归找某个键的值。

    接口偶尔会把结果包一层（data / output / images……），
    与其猜它长什么样，不如按名字直接找。
    """
    if isinstance(value, dict):
        found = value.get(key_name)
        if found is not None:
            if not url_only or (isinstance(found, str) and found.startswith("http")):
                return found
        for child in value.values():
            result = _find_key_recursively(child, key_name, url_only=url_only)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _find_key_recursively(child, key_name, url_only=url_only)
            if result is not None:
                return result
    return None


def _guess_extension(content_type: str, url: str) -> str:
    """根据响应头/网址判断该存成什么后缀，避免"jpg 内容存成 .png"。"""
    content_type = (content_type or "").lower()
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"

    url_suffix = Path(url.split("?")[0]).suffix.lower()
    if url_suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return ".jpg" if url_suffix == ".jpeg" else url_suffix
    return ".jpg"


def _safe_file_stem(name: str) -> str:
    """把名字里 Windows 不允许的字符换成下划线；中文允许保留。"""
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("._")
    return cleaned or "illustration"


def get_api_image_size(api_model: str, image_type: str) -> tuple[int, int]:
    """从集中配置读取指定模型和图片类型的宽高。"""

    config = get_cloud_api_config(api_model)
    try:
        return config.image_sizes[image_type]
    except KeyError as error:
        allowed = "、".join(config.image_sizes)
        raise ApiImageError(
            f"不支持的 image_type：{image_type}；只能填写 {allowed}。"
        ) from error


# ---------------------------------------------------------------------------
# 四、核心函数：调用云端接口生成图片
# ---------------------------------------------------------------------------


def generate_illustration_api(
    prompt: str,
    params: ApiImageParams = DEFAULT_API_PARAMS,
    settings: ApiImageSettings = DEFAULT_API_SETTINGS,
    name_prefix: str = "illustration_api",
) -> dict[str, Any]:
    """生成一张图片并保存，返回一份"结果说明"字典（字段与本地版对齐）。

    参数
    ----
    prompt      : 提示词。这个接口没有负面提示词，不想要的东西也写在这里。
    params      : 模型名、尺寸、seed、水印开关
    settings    : 连接类配置（接口地址、Key 名字、保存目录、超时）
    name_prefix : 文件名前缀

    返回
    ----
    {"paths": [...], "seeds": [...], "elapsed_seconds": 12.3,
     "size": "2K", "model": "...", "backend": "cloud_api", "source_url": "..."}
    """
    if not prompt or not prompt.strip():
        raise ApiImageError("prompt 不能为空，至少写一句要画什么。")

    api_key = load_api_key(settings)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # 只传当前模型支持的单图生成参数。部分 Seedream 版本不支持
    # sequential_image_generation，即使值为 disabled 也会直接返回 400。
    payload = {
        "model": params.model,
        "prompt": prompt.strip(),
        "size": params.size,
        **SEEDREAM_CONFIG.request_defaults,
    }
    if params.seed >= 0:
        payload["seed"] = params.seed

    started_at = time.time()

    # 第一段请求：让云端开始画，并拿到临时图片网址。
    try:
        response = requests.post(
            settings.endpoint,
            headers=headers,
            json=payload,
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError as error:
        raise ApiImageError(
            "连不上云端接口，检查一下网络（是否要开代理 / DNS 是否正常）。"
        ) from error
    except requests.exceptions.HTTPError as error:
        error_response = error.response
        status_code = getattr(error_response, "status_code", "?")
        response_text = getattr(error_response, "text", "")

        # 尽量把接口自己给的错误码挖出来，方便我们知道到底哪一步出的问题。
        error_code = ""
        try:
            error_code = error_response.json().get("error", {}).get("code", "") or ""
        except (ValueError, AttributeError):
            pass

        if "SensitiveContent" in str(error_code) or "SensitiveContent" in response_text:
            raise ApiImageError(
                "云端内容审核把这次生成拦截了（错误码里带 SensitiveContent）。\n"
                "这不是代码问题：把提示词改得含蓄一些，或去掉敏感元素再试。\n"
                f"接口原始响应：{response_text[:500]}"
            ) from error
        if status_code in (401, 403):
            raise ApiImageError(
                f"鉴权失败（HTTP {status_code}）：API Key 可能填错、过期或没有权限。\n"
                f"接口原始响应：{response_text[:500]}"
            ) from error
        if status_code == 429:
            raise ApiImageError(
                "请求太频繁或余额不足（HTTP 429）。稍等一会儿再试，或去平台看看余额。\n"
                f"接口原始响应：{response_text[:500]}"
            ) from error

        raise ApiImageError(
            f"云端接口返回错误状态码 {status_code}：\n{response_text[:800]}"
        ) from error
    except requests.exceptions.RequestException as error:
        raise ApiImageError(f"请求云端接口失败：{error}") from error

    results = _parse_api_response(response)
    image_url = _find_key_recursively(results, "url", url_only=True)
    if not image_url:
        raise ApiImageError(f"接口没有返回图片网址，完整响应：{str(results)[:500]}")

    # 第二段请求：立刻把临时网址里的图片下载下来。
    try:
        image_response = requests.get(image_url, timeout=settings.download_timeout)
        image_response.raise_for_status()
    except requests.exceptions.RequestException as error:
        raise ApiImageError(f"图片下载失败（临时网址可能已过期）：{error}") from error

    elapsed = time.time() - started_at

    extension = _guess_extension(
        image_response.headers.get("Content-Type", ""), image_url
    )
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 云端不一定回传真正的 seed，那就用一小段随机字符保证文件名不重复。
    seed_value = _find_key_recursively(results, "seed")
    if not isinstance(seed_value, int):
        seed_value = None
    name_suffix = str(seed_value) if seed_value is not None else uuid4().hex[:8]
    output_path = output_dir / (
        f"{_safe_file_stem(name_prefix)}_"
        f"{datetime.now():%Y%m%d_%H%M%S}_{name_suffix}{extension}"
    )
    output_path.write_bytes(image_response.content)

    return {
        "paths": [str(output_path)],
        "seeds": [seed_value] if seed_value is not None else [],
        "elapsed_seconds": round(elapsed, 1),
        "size": params.size,
        "model": params.model,
        "backend": "cloud_api",
        "source_url": image_url,
    }


def generate_illustration_flux(
    prompt: str,
    image_type: Literal["character", "scene"],
    seed: int = -1,
    settings: ApiImageSettings = DEFAULT_API_SETTINGS,
    name_prefix: str = "illustration_flux",
) -> dict[str, Any]:
    """调用 Flux 异步接口，轮询完成后下载图片。"""

    if not prompt or not prompt.strip():
        raise ApiImageError("prompt 不能为空，至少写一句要画什么。")

    config = get_cloud_api_config("flux")
    width, height = get_api_image_size("flux", image_type)
    api_key = load_api_key(settings)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "prompt": prompt.strip(),
        "width": width,
        "height": height,
        **config.request_defaults,
    }
    if seed >= 0:
        payload["seed"] = seed

    started_at = time.time()
    try:
        response = requests.post(
            config.endpoint,
            headers=headers,
            json=payload,
            timeout=settings.request_timeout,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as error:
        response_text = getattr(getattr(error, "response", None), "text", "")
        raise ApiImageError(
            f"提交 Flux 任务失败：{error}\n{response_text[:800]}"
        ) from error

    task_documents = _parse_api_response(response)
    task_data = task_documents[0]
    task_id = task_data.get("id")
    if not isinstance(task_id, str) or not task_id:
        raise ApiImageError(f"Flux 接口没有返回任务 ID：{str(task_data)[:500]}")

    image_url = ""
    returned_seed: int | None = None
    deadline = time.monotonic() + settings.request_timeout[1]
    while time.monotonic() < deadline:
        try:
            result_response = requests.get(
                config.result_endpoint,
                headers=headers,
                params={"id": task_id},
                timeout=settings.request_timeout,
            )
            result_response.raise_for_status()
        except requests.exceptions.RequestException as error:
            response_text = getattr(getattr(error, "response", None), "text", "")
            raise ApiImageError(
                f"查询 Flux 任务失败：{error}\n{response_text[:800]}"
            ) from error

        result_data = _parse_api_response(result_response)[0]
        status = str(result_data.get("status", "")).lower()
        if status == "ready":
            result = result_data.get("result") or {}
            image_url = result.get("sample", "")
            seed_value = result.get("seed")
            returned_seed = seed_value if isinstance(seed_value, int) else None
            break
        if status in {"error", "failed", "failure"}:
            raise ApiImageError(f"Flux 任务失败：{str(result_data)[:800]}")
        time.sleep(2)

    if not image_url:
        raise ApiImageError(
            f"Flux 任务等待超时或没有返回图片 URL，task_id={task_id}"
        )

    try:
        image_response = requests.get(image_url, timeout=settings.download_timeout)
        image_response.raise_for_status()
    except requests.exceptions.RequestException as error:
        raise ApiImageError(f"下载 Flux 图片失败：{error}") from error

    extension = _guess_extension(
        image_response.headers.get("Content-Type", ""), image_url
    )
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    name_suffix = (
        str(returned_seed) if returned_seed is not None else uuid4().hex[:8]
    )
    output_path = output_dir / (
        f"{_safe_file_stem(name_prefix)}_"
        f"{datetime.now():%Y%m%d_%H%M%S}_{name_suffix}{extension}"
    )
    output_path.write_bytes(image_response.content)

    return {
        "paths": [str(output_path)],
        "seeds": [returned_seed] if returned_seed is not None else [],
        "elapsed_seconds": round(time.time() - started_at, 1),
        "size": f"{width}x{height}",
        "model": config.model,
        "backend": "cloud_api",
        "task_id": task_id,
        "source_url": image_url,
    }


def check_api_ready(settings: ApiImageSettings = DEFAULT_API_SETTINGS) -> str:
    """体检：只看 Key 有没有配好，不联网、不花钱。"""
    lines: list[str] = ["已配置的云端生图模型："]
    for key, config in CLOUD_IMAGE_APIS.items():
        lines.append(f"- {key}: {config.display_name}（{config.endpoint}）")
    try:
        api_key = load_api_key(settings)
    except ApiImageError as error:
        lines.append(str(error))
        return "\n".join(lines)

    source = (
        "系统环境变量"
        if os.environ.get(settings.api_key_env_name, "").strip()
        else str(settings.env_file)
    )
    lines.append(f"API Key：已读到（来自 {source}，长度 {len(api_key)} 位）")
    lines.append(f"图片保存目录：{settings.output_dir}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 五、交给 Agent 调用的 Tool（docstring 就是给模型看的说明书）
# ---------------------------------------------------------------------------


def _run_cloud_image_tool(
    *,
    prompt: str,
    image_type: Literal["character", "scene"],
    api_model: str,
    seed: int,
    output_prefix: str,
    output_dir: Path,
) -> str:
    """执行云端生图；output_dir 由程序绑定，不暴露给 Agent。"""

    try:
        config = get_cloud_api_config(api_model)
        settings = replace(DEFAULT_API_SETTINGS, output_dir=Path(output_dir))
        if config.protocol == "direct_url":
            width, height = get_api_image_size(api_model, image_type)
            params = replace(
                DEFAULT_API_PARAMS,
                model=config.model,
                size=f"{width}x{height}",
                seed=seed,
            )
            settings = replace(settings, endpoint=config.endpoint)
            result = generate_illustration_api(
                prompt=prompt,
                params=params,
                settings=settings,
                name_prefix=output_prefix,
            )
        elif config.protocol == "async_task":
            result = generate_illustration_flux(
                prompt=prompt,
                image_type=image_type,
                seed=seed,
                settings=settings,
                name_prefix=output_prefix,
            )
        else:  # pragma: no cover - 配置类型已经由 Literal 限定
            raise ApiImageError(f"尚未实现的 API 协议：{config.protocol}")
    except (ApiImageError, ValueError) as error:
        return f"画图失败：{error}"

    path_text = "；".join(result["paths"])
    return (
        f"插画已生成并保存到：{path_text}\n"
        f"model={result['model']}，尺寸 {result['size']}，"
        f"seed={result['seeds'] or ['未回传']}，"
        f"耗时 {result['elapsed_seconds']} 秒（云端接口）。"
    )


@tool
def draw_illustration_cloud(
    prompt: str,
    image_type: Literal["character", "scene"],
    api_model: str = DEFAULT_CLOUD_IMAGE_API,
    seed: int = -1,
    output_prefix: str = "illustration_api",
) -> str:
    """用【云端接口】画一张插画（不需要显卡），保存到 story_agent/pictures/。

    什么时候用：需要为故事桥段配插画，但本机没有可用的 Forge 时用本工具；
    如果本机 Forge 正常，优先用 draw_illustration_local（不花云端的钱）。

    和 draw_illustration_local 的区别（选后端时看这一段）：
        - 本工具没有 negative_prompt 参数。不想要的东西写进 prompt，
          而且要"用替代法，不用否定法"：别写 "no text"，
          改成正向描述把来源堵掉，例如 "blank book cover, plain wooden sign"。
        - 本工具不支持姿势参考图（没有 ControlNet）。
        - 有内容审核，可能被拦截。
        - Seedream 的 seed 复现较弱；Flux 支持用非负 seed 尝试复现。

    注意：
        1. 调用一次要花几秒到几十秒，并且是按张计费的，请一次只画一张，
           不要用同一段提示词反复调用。
        2. 云端有内容审核。若返回"内容审核拦截"，说明提示词太敏感，
           请改写得更含蓄后再试，不要原样重试。

    参数：
        prompt（必填）：画面描述。建议英文关键词、逗号分隔，
            例如 "1girl, reading a book, cozy library, warm light, anime illustration"。
        image_type（必填）：根据画面主体二选一：
            - "character"：人物剧情竖图；
            - "scene"：场景剧情横图。
            不要自行填写 size。
        api_model：云端模型二选一：
            - "seedream"：Seedream 5.0 Pro，理解复杂自然语言较好；
            - "flux"：Flux-2-Klein-9b，支持固定 seed 和自定义宽高。
        seed：随机种子。默认 -1 表示随机；云端不一定保证同一 seed 完全一致。
        output_prefix：文件名前缀，可以写桥段名，例如 "chapter1_scene2"。

    返回：一段文字，包含生成好的图片绝对路径、耗时（失败时返回失败原因）。
    """
    return _run_cloud_image_tool(
        prompt=prompt,
        image_type=image_type,
        api_model=api_model,
        seed=seed,
        output_prefix=output_prefix,
        output_dir=PICTURES_DIR,
    )


def build_cloud_image_tool(output_dir: Path = PICTURES_DIR):
    """把当前故事的图片目录绑定到云端 Tool，不把路径暴露给 Agent。"""

    @tool("draw_illustration_cloud", description=draw_illustration_cloud.description)
    def configured_cloud_image_tool(
        prompt: str,
        image_type: Literal["character", "scene"],
        api_model: str = DEFAULT_CLOUD_IMAGE_API,
        seed: int = -1,
        output_prefix: str = "illustration_api",
    ) -> str:
        return _run_cloud_image_tool(
            prompt=prompt,
            image_type=image_type,
            api_model=api_model,
            seed=seed,
            output_prefix=output_prefix,
            output_dir=output_dir,
        )

    return configured_cloud_image_tool


# ---------------------------------------------------------------------------
# 六、单独运行本文件 = 自测（先体检，再画一张图）
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(check_api_ready())

    demo_prompt = (
        "1girl, sitting by a window in a cozy library, holding an open book, "
        "a cup of tea on the table, warm afternoon sunlight, anime illustration style, "
        "detailed background, soft colors, no text"
    )

    # 想临时换模型 / 换尺寸，不用改文件里的默认值，照着下面两行写即可：
    #     my_params = replace(DEFAULT_API_PARAMS, model="别的模型名", size="2496x1664")
    #     generate_illustration_api(prompt=demo_prompt, params=my_params)
    demo_result = generate_illustration_api(
        prompt=demo_prompt,
        name_prefix="api_selftest",
    )
    print(json.dumps(demo_result, ensure_ascii=False, indent=2))
