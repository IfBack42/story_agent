"""支持多轮记忆、故事存档和按故事保存图片的插画 Agent。

当前只完成一条流水线：
    用户提示词
    -> 提示词优化 Tool
    -> 本地/自建服务器模型或云端 API 生图 Tool
    -> 返回图片路径

运行时由 InMemorySaver 管理状态；每轮结束后再保存到故事目录的 JSON，
因此程序重启后可以按故事名称恢复历史，并继续使用原 session_id。
"""

from __future__ import annotations

import os
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from story_session import (
    HISTORY_DATA_DIR,
    choose_story_session,
    save_story_session,
)
from tools.api_image_tool import build_cloud_image_tool
from tools.local_image_tool import build_local_image_tool
from tools.localimgconfig import GenerationMode
from tools.prompt_optimizer_tool import build_prompt_optimizer_tool


MODEL_NAME = "deepseek-v4-flash"
LOCAL_IMAGE_MODEL = "wai"
LOCAL_IMAGE_PORT: int | None = None  # None = 使用模型注册的默认端口
LOCAL_IMAGE_MODE: GenerationMode = "txt2img"
BASE_DIR = Path(__file__).resolve().parent
AGENT_SYSTEM_PROMPT_PATH = BASE_DIR / "prompt_guides" / "agent_system_promt.txt"

# checkpointer 是所有 Agent 实例共用的“存档柜”。run_agent 每轮会重新构建
# Agent，因此这里必须放在模块级；如果在 build_agent 内创建，第二轮会拿到空存档。
MEMORY_CHECKPOINTER = InMemorySaver()


def load_agent_system_prompt(path: Path = AGENT_SYSTEM_PROMPT_PATH) -> str:
    """从外部文本文件读取主 Agent 的系统提示词。"""

    if not path.is_file():
        raise FileNotFoundError(f"找不到主 Agent 系统提示词文件：{path}")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"主 Agent 系统提示词文件不能为空：{path}")
    return content


SYSTEM_PROMPT = load_agent_system_prompt()

TOOL_PROGRESS = {
    "optimize_prompt_for_illustration": (
        "[进度 1/2] 正在读取目标模型注册的规则并优化提示词……",
        "[进度 1/2] 提示词优化完成。",
    ),
    "draw_illustration_local": (
        "[进度 2/2] 正在调用已配置的本地生图模型，请稍候……",
        "[进度 2/2] 本地生图模型已完成处理。",
    ),
    "draw_illustration_cloud": (
        "[进度 2/2] 正在调用云端 API 生成插画，请稍候……",
        "[进度 2/2] 云端 API 已完成处理。",
    ),
}


def build_model() -> ChatOpenAI:
    """创建供主 Agent 和提示词优化 Tool 共用的 LangChain LLM。"""

    base_url = os.environ.get("dpsk_url", "").strip()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError("缺少 dpsk_url 或 DEEPSEEK_API_KEY 环境变量。")

    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=MODEL_NAME,
        temperature=0.2,
        timeout=180,
        max_tokens=2000,
        # 主 Agent 只负责选择和串联工具，不需要 Thinking 模式。
        # 关闭后可以避免 DeepSeek Thinking 对 tool_choice 的限制。
        extra_body={"thinking": {"type": "disabled"}},
    )


def build_agent(
    local_image_model: str = LOCAL_IMAGE_MODEL,
    local_image_port: int | None = LOCAL_IMAGE_PORT,
    local_image_mode: GenerationMode = LOCAL_IMAGE_MODE,
    image_output_dir: Path | None = None,
):
    """创建同时支持本地与云端生图的 Agent。"""

    model = build_model()
    # optimizer 会用 image_backend + image_model 查注册表，再由模型配置决定
    # 读取哪套提示词模板。这里绑定本地模型，防止 Agent 优化 A 却调用 B。
    prompt_optimizer = build_prompt_optimizer_tool(
        model,
        local_image_model=local_image_model,
    )
    local_image_tool = build_local_image_tool(
        model_name=local_image_model,
        port=local_image_port,
        mode=local_image_mode,
        output_dir=image_output_dir or (BASE_DIR / "pictures"),
    )
    cloud_image_tool = build_cloud_image_tool(
        output_dir=image_output_dir or (BASE_DIR / "pictures")
    )

    return create_agent(
        model=model,
        tools=[prompt_optimizer, local_image_tool, cloud_image_tool],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=MEMORY_CHECKPOINTER,
    )


def build_session_config(thread_id: str) -> dict:
    """把会话编号包装成 LangGraph checkpointer 需要的配置。"""

    if not thread_id or not thread_id.strip():
        raise ValueError("thread_id 不能为空。")
    return {"configurable": {"thread_id": thread_id.strip()}}


def _message_text(content) -> str:
    """把模型可能返回的字符串或内容块统一转成可打印文本。"""

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content)


def stream_agent_progress(
    agent,
    agent_input: dict,
    config: dict,
    show_progress: bool = True,
) -> str:
    """同时流式打印模型文字和工具步骤，并返回最终完整正文。

    messages 模式负责模型 token；updates 模式负责节点和 Tool 状态。
    只打印主 Agent 的 model 节点，避免把 Tool 内部的提示词优化 LLM 输出也打印出来。
    """

    if show_progress:
        print("[Agent] 已收到请求，正在判断下一步操作……", flush=True)

    final_text = ""
    text_line_open = False

    for stream_mode, stream_data in agent.stream(
        agent_input,
        config=config,
        stream_mode=["messages", "updates"],
    ):
        if stream_mode == "messages":
            message_chunk, metadata = stream_data

            # create_agent 的主模型节点名为 model。Tool 内部的 LLM 调用通常属于
            # tools 节点，过滤后不会把结构化 JSON 等内部输出混进最终正文。
            if metadata.get("langgraph_node") != "model":
                continue
            if not isinstance(message_chunk, AIMessageChunk):
                continue

            chunk_text = _message_text(message_chunk.content)
            if chunk_text and show_progress:
                print(chunk_text, end="", flush=True)
                text_line_open = not chunk_text.endswith(("\n", "\r"))
            continue

        if stream_mode != "updates":
            continue

        update = stream_data
        for node_update in update.values():
            for message in node_update.get("messages", []):
                if isinstance(message, AIMessage):
                    if message.tool_calls:
                        for tool_call in message.tool_calls:
                            tool_name = tool_call.get("name", "未知工具")
                            if show_progress:
                                if text_line_open:
                                    print(flush=True)
                                    text_line_open = False
                                start_text = TOOL_PROGRESS.get(
                                    tool_name,
                                    (f"[进度] 正在调用 {tool_name}……", ""),
                                )[0]
                                print(start_text, flush=True)
                    else:
                        text = _message_text(message.content).strip()
                        if text:
                            final_text = text

                elif isinstance(message, ToolMessage) and show_progress:
                    if text_line_open:
                        print(flush=True)
                        text_line_open = False
                    tool_name = message.name or "未知工具"
                    finish_text = TOOL_PROGRESS.get(
                        tool_name,
                        ("", f"[进度] {tool_name} 已返回结果。"),
                    )[1]
                    if finish_text:
                        print(finish_text, flush=True)

                    tool_result = _message_text(message.content).strip()
                    # 生图 Tool 约定失败结果以“画图失败：”开头。不能只搜索
                    # “失败”二字，否则优化说明中的“常见失败模式”也会被误报。
                    if tool_result.startswith("画图失败："):
                        print(f"[工具错误] {tool_result}", flush=True)

    if show_progress and text_line_open:
        print(flush=True)

    return final_text


def run_agent(
    prompt: str,
    local_image_model: str = LOCAL_IMAGE_MODEL,
    local_image_port: int | None = LOCAL_IMAGE_PORT,
    local_image_mode: GenerationMode = LOCAL_IMAGE_MODE,
    show_progress: bool = True,
    thread_id: str = "default-session",
    image_output_dir: Path | None = None,
) -> str:
    """运行一轮 Agent；相同 thread_id 的多次调用会共享对话历史。"""

    if not prompt or not prompt.strip():
        raise ValueError("prompt 不能为空。")

    agent = build_agent(
        local_image_model=local_image_model,
        local_image_port=local_image_port,
        local_image_mode=local_image_mode,
        image_output_dir=image_output_dir,
    )
    agent_input = {
        "messages": [
            {
                "role": "user",
                "content": prompt.strip(),
            }
        ]
    }
    config = build_session_config(thread_id)
    return stream_agent_progress(agent, agent_input, config, show_progress)


def run_chat_loop(
    local_image_model: str = LOCAL_IMAGE_MODEL,
    local_image_port: int | None = LOCAL_IMAGE_PORT,
    local_image_mode: GenerationMode = LOCAL_IMAGE_MODE,
    history_root: Path = HISTORY_DATA_DIR,
    show_progress: bool = True,
) -> None:
    """选择或新建故事，恢复历史，并在每轮结束后保存 JSON。"""

    story = choose_story_session(history_root)

    agent = build_agent(
        local_image_model=local_image_model,
        local_image_port=local_image_port,
        local_image_mode=local_image_mode,
        image_output_dir=story.pictures_dir,
    )
    config = build_session_config(story.session_id)

    # 新进程中的 InMemorySaver 是空的。第一次提问时把 JSON 读出的历史与
    # 新问题一起交给 Agent，之后继续依靠同一个 thread_id 读取内存检查点。
    checkpoint_messages = list(agent.get_state(config).values.get("messages", []))
    needs_history_restore = bool(story.messages) and not checkpoint_messages

    print(f"\n已进入故事：{story.story_name}")
    print(f"session_id：{story.session_id}")
    print(f"已恢复 {sum(message.type == 'human' for message in story.messages)} 轮对话。")
    print(f"故事目录：{story.folder}")
    print("输入 q 退出。")
    while True:
        try:
            prompt = input("\n:").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n会话已退出。")
            break

        if prompt.lower() == "q":
            print("会话已退出。")
            break
        if not prompt:
            print("请输入内容，或输入 q 退出。")
            continue

        current_message = {"role": "user", "content": prompt}
        input_messages = (
            [*story.messages, current_message]
            if needs_history_restore
            else [current_message]
        )
        agent_input = {"messages": input_messages}
        stream_agent_progress(agent, agent_input, config, show_progress)

        state = agent.get_state(config)
        story.messages = list(state.values.get("messages", []))
        save_story_session(story)
        needs_history_restore = False
        print(
            f"[已保存] {story.story_name}："
            f"{sum(message.type == 'human' for message in story.messages)} 轮对话。",
            flush=True,
        )


if __name__ == "__main__":
    local_image_model = "wai"          # wai / qwen_image_2_1
    local_image_port = None             # None = 使用注册表里的默认端口
    local_image_mode = "txt2img"        # WAI: txt2img/openpose；千问: txt2img/img2img

    run_chat_loop(
        local_image_model=local_image_model,
        local_image_port=local_image_port,
        local_image_mode=local_image_mode,
    )
