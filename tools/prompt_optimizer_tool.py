"""插画提示词优化 Tool。

核心流程只有四步：
    查找目标模型配置 -> 读取该模型登记的提示词文件 -> 调用 LLM -> 返回结构化结果。

本模块不负责创建 LLM。调用方必须显式传入 LangChain 的 BaseChatModel，
例如 ChatOpenAI 或 ChatOllama。这样模型配置留在主程序中，Tool 只负责提示词优化。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from pydantic import BaseModel, Field, ValidationError

from tools.apiimgconfig import CloudImageApiConfig, get_cloud_api_config
from tools.localimgconfig import (
    DEFAULT_LOCAL_IMAGE_MODEL,
    LocalImageModelConfig,
    get_local_image_config,
)

# TODO 提示词换大众版
BASE_DIR = Path(__file__).resolve().parent.parent
GUIDE_DIR = BASE_DIR / "prompt_guides"
DEFAULT_GUIDE_PATH = GUIDE_DIR / "WAI_Illustrious_v15_Public_Guide.md"
DEFAULT_LOCAL_SYSTEM_PROMPT_PATH = GUIDE_DIR / "llm_system_prompt_local.txt"
DEFAULT_CLOUD_SYSTEM_PROMPT_PATH = GUIDE_DIR / "llm_system_prompt_api.txt"

ImageBackend = Literal["local", "cloud"]
ImageModelConfig = LocalImageModelConfig | CloudImageApiConfig


class PromptOptimizerError(RuntimeError):
    """提示词优化失败。"""


@dataclass(frozen=True)
class PromptOptimizerSettings:
    """提示词文件所在目录；具体文件名由每个生图模型配置决定。"""

    prompt_guide_dir: Path = GUIDE_DIR


DEFAULT_OPTIMIZER_SETTINGS = PromptOptimizerSettings()

# 最近一次优化调用的耗时，包括失败的调用。
LAST_ELAPSED_SECONDS: float = 0.0


class OptimizedPrompt(BaseModel):
    """LLM 必须返回的结构。"""

    optimized_prompt: str = Field(
        description="适合当前目标生图后端的英文正向提示词，可直接传给生图工具"
    )
    optimized_negative_prompt: str = Field(
        description="优化后的负面提示词；目标后端不支持时返回空字符串"
    )
    changes: list[str] = Field(
        default_factory=list,
        description="3~6 条关键修改说明，使用中文",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="冲突或不确定之处，使用中文；没有则为空数组",
    )


# 缓存键包含修改时间：文件未修改时不用重复读取，修改后会自动读取新版本。
_TEXT_CACHE: dict[tuple[str, float], str] = {}


def load_text_file(path: Path, file_label: str) -> str:
    """读取并缓存 UTF-8 文本配置。"""

    path = Path(path)
    if not path.is_file():
        raise PromptOptimizerError(
            f"找不到{file_label}：{path}\n"
            f"请把文件放到 {GUIDE_DIR}，或修改 PromptOptimizerSettings。"
        )

    key = (str(path), path.stat().st_mtime)
    if key not in _TEXT_CACHE:
        _TEXT_CACHE[key] = path.read_text(encoding="utf-8")
    content = _TEXT_CACHE[key].strip()
    if not content:
        raise PromptOptimizerError(f"{file_label}不能为空：{path}")
    return content


def load_model_guide(guide_path: Path = DEFAULT_GUIDE_PATH) -> str:
    """读取并缓存模型提示词手册。"""

    return load_text_file(guide_path, "模型规范文档")


def load_llm_system_prompt(
    prompt_path: Path = DEFAULT_LOCAL_SYSTEM_PROMPT_PATH,
) -> str:
    """读取并缓存提示词优化 LLM 的系统提示词。"""

    return load_text_file(prompt_path, "提示词优化 LLM 系统提示词")


def build_system_instruction(system_prompt: str, guide_text: str = "") -> str:
    """把优化要求和模型手册组成系统消息。"""

    if not guide_text:
        return system_prompt
    return system_prompt + "\n\n# 本地模型提示词手册\n" + guide_text


def get_optimizer_instruction(
    image_backend: ImageBackend,
    image_model: str,
    settings: PromptOptimizerSettings = DEFAULT_OPTIMIZER_SETTINGS,
) -> tuple[str, ImageModelConfig]:
    """按后端和模型名读取该模型登记的提示词规则。"""

    config = resolve_image_model_config(image_backend, image_model)
    system_prompt_path = settings.prompt_guide_dir / config.prompt_system_file
    system_prompt = load_llm_system_prompt(system_prompt_path)
    guide_text = ""
    if config.prompt_guide_file:
        guide_path = settings.prompt_guide_dir / config.prompt_guide_file
        guide_text = load_model_guide(guide_path)
    return build_system_instruction(system_prompt, guide_text), config


def resolve_image_model_config(
    image_backend: ImageBackend,
    image_model: str,
) -> ImageModelConfig:
    """用后端选择注册表，再用模型名取得唯一配置。"""

    if not image_model or not image_model.strip():
        raise PromptOptimizerError("image_model 不能为空，必须填写已注册模型名。")
    try:
        if image_backend == "local":
            return get_local_image_config(image_model)
        if image_backend == "cloud":
            return get_cloud_api_config(image_model)
    except ValueError as error:
        raise PromptOptimizerError(str(error)) from error
    raise PromptOptimizerError(
        f"不支持的 image_backend：{image_backend}；只能填写 local 或 cloud。"
    )


def build_user_request(
    prompt: str,
    negative_prompt: str,
    goal: str,
    image_backend: ImageBackend,
    config: ImageModelConfig,
) -> str:
    """把本次输入整理成给 LLM 的用户消息。"""

    default_goal = (
        "精简、消重、重排并补充针对性负面提示词"
        if config.supports_negative_prompt
        else "改写为适合目标生图模型的简洁自然语言视觉描述"
    )
    backend_capability = (
        "该模型支持独立 negative_prompt，请生成针对性负面提示词。"
        if config.supports_negative_prompt
        else "该模型不使用独立 negative_prompt；请将 optimized_negative_prompt 设为空字符串。"
    )
    return (
        f"目标生图后端：{image_backend}\n"
        f"目标生图模型：{config.key}（{config.display_name}）\n"
        f"后端能力：{backend_capability}\n"
        f"正向提示词：{prompt}\n"
        f"负面提示词：{negative_prompt.strip() or '（空）'}\n"
        f"优化目标：{goal.strip() or default_goal}"
    )


def _require_langchain_llm(llm: BaseChatModel) -> None:
    """拒绝普通对象和完整 Agent，只接受 LangChain 聊天模型。"""

    if not isinstance(llm, BaseChatModel):
        raise PromptOptimizerError(
            "llm 必须是 LangChain 的 BaseChatModel，例如 ChatOpenAI 或 ChatOllama；"
            "不要传入完整 Agent。"
        )


def optimize_prompt(
    prompt: str,
    llm: BaseChatModel,
    image_backend: ImageBackend,
    image_model: str,
    negative_prompt: str = "",
    goal: str = "",
    settings: PromptOptimizerSettings = DEFAULT_OPTIMIZER_SETTINGS,
    bound_local_image_model: str | None = None,
) -> dict[str, Any]:
    """使用指定的 LangChain LLM 优化提示词。"""

    global LAST_ELAPSED_SECONDS

    if not prompt or not prompt.strip():
        raise PromptOptimizerError("prompt 不能为空，至少写一句想画什么。")
    _require_langchain_llm(llm)

    if image_backend == "local" and bound_local_image_model:
        requested = image_model.strip().lower()
        bound = bound_local_image_model.strip().lower()
        if requested != bound:
            raise PromptOptimizerError(
                f"当前程序入口绑定的本地模型是 {bound_local_image_model}，"
                f"不能用 {image_model} 的提示词模板。"
            )

    system_instruction, config = get_optimizer_instruction(
        image_backend,
        image_model,
        settings,
    )
    messages = [
        ("system", system_instruction),
        (
            "human",
            build_user_request(
                prompt=prompt.strip(),
                negative_prompt=negative_prompt,
                goal=goal,
                image_backend=image_backend,
                config=config,
            ),
        ),
    ]

    started_at = time.perf_counter()
    try:
        # DeepSeek Chat Completions 支持 json_object，但不支持 OpenAI 的
        # json_schema；Thinking 模式也不能强制指定具体 tool_choice。
        structured_llm = llm.with_structured_output(
            OptimizedPrompt,
            method="json_mode",
        )
        raw_result = structured_llm.invoke(messages)
        result = (
            raw_result
            if isinstance(raw_result, OptimizedPrompt)
            else OptimizedPrompt.model_validate(raw_result)
        )
    except ValidationError as error:
        raise PromptOptimizerError(f"LLM 返回的数据结构不符合要求：{error}") from error
    except Exception as error:
        raise PromptOptimizerError(
            f"调用提示词优化 LLM 失败：{type(error).__name__}: {error}"
        ) from error
    finally:
        LAST_ELAPSED_SECONDS = round(time.perf_counter() - started_at, 1)

    result_dict = result.model_dump()
    if not config.supports_negative_prompt:
        result_dict["optimized_negative_prompt"] = ""
    result_dict.update(
        {
            "image_backend": image_backend,
            "image_model": config.key,
            "prompt_system_file": config.prompt_system_file,
            "prompt_guide_file": config.prompt_guide_file or "",
        }
    )
    return result_dict


def build_prompt_optimizer_tool(
    llm: BaseChatModel,
    settings: PromptOptimizerSettings = DEFAULT_OPTIMIZER_SETTINGS,
    *,
    local_image_model: str = DEFAULT_LOCAL_IMAGE_MODEL,
):
    """绑定 LLM，只向 Agent 暴露提示词业务参数。"""

    _require_langchain_llm(llm)

    local_config = get_local_image_config(local_image_model)
    tool_description = (
        "在调用生图工具前优化插画提示词。必须同时填写 image_backend 和 "
        "image_model；工具会从该模型的注册配置中自动选择提示词模板，不能由你"
        "自行决定模板。调用 draw_illustration_local 时，image_backend 必须是 "
        f"'local'，image_model 必须是 '{local_config.key}'。调用 "
        "draw_illustration_cloud 时，image_backend 必须是 'cloud'，image_model "
        "必须与随后传给云端生图工具的 api_model 完全相同。优化完成后，必须调用"
        "对应后端且同一模型的生图工具。"
    )

    @tool("optimize_prompt_for_illustration", description=tool_description)
    def optimize_prompt_for_illustration(
        prompt: str,
        image_backend: ImageBackend,
        image_model: str,
        negative_prompt: str = "",
        goal: str = "",
    ) -> dict[str, Any]:
        """根据下一步使用的生图模型配置自动选择规则并优化提示词。"""

        return optimize_prompt(
            prompt=prompt,
            llm=llm,
            image_backend=image_backend,
            image_model=image_model,
            negative_prompt=negative_prompt,
            goal=goal,
            settings=settings,
            bound_local_image_model=local_config.key,
        )

    return optimize_prompt_for_illustration


if __name__ == "__main__":
    # 手动测试入口：只有直接运行本文件时才会创建并调用 DeepSeek。
    # 正常导入 Tool 时不会执行这里，也不会自动创建任何 LLM。
    import json
    import os

    from langchain_openai import ChatOpenAI

    base_url = os.environ.get("dpsk_url", "").strip()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError("缺少 dpsk_url 或 DEEPSEEK_API_KEY 环境变量。")

    test_llm = ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model="deepseek-v4-flash",
        temperature=0.2,
        timeout=180,
        max_tokens=1500,
    )
    test_tool = build_prompt_optimizer_tool(test_llm, local_image_model="wai")


    prompt = """

    """


    test_result = test_tool.invoke(
        {
            "prompt": prompt,
            "image_backend": "local",
            "image_model": "wai",
            "negative_prompt": "",
            "goal": "精简并保持画面意图",
        }
    )

    print(json.dumps(test_result, ensure_ascii=False, indent=2))
    print(f"耗时：{LAST_ELAPSED_SECONDS} 秒")
