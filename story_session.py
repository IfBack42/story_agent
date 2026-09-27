"""故事会话的创建、选择、读取与 JSON 保存。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict


BASE_DIR = Path(__file__).resolve().parent
HISTORY_DATA_DIR = BASE_DIR / "history_data"
CONVERSATION_FILE_NAME = "conversation.json"
PICTURES_DIR_NAME = "pictures"


def current_time() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_folder_name(story_name: str) -> str:
    """保留可读的中文名称，同时移除 Windows 文件夹禁用字符。"""

    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", story_name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise ValueError("故事名称不能只包含空格或文件名禁用字符。")
    return cleaned[:80].rstrip(" .")


def _validate_session_id(session_id: str) -> str:
    """确认 session_id 是完整 UUID，而不是由故事名称拼出来的临时编号。"""

    try:
        return str(UUID(session_id))
    except (ValueError, AttributeError) as error:
        raise ValueError(f"无效的 session_id：{session_id}") from error


@dataclass
class StorySession:
    story_name: str
    session_id: str
    folder: Path
    created_at: str
    updated_at: str
    messages: list[BaseMessage] = field(default_factory=list)

    @property
    def conversation_file(self) -> Path:
        return self.folder / CONVERSATION_FILE_NAME

    @property
    def pictures_dir(self) -> Path:
        return self.folder / PICTURES_DIR_NAME


def save_story_session(session: StorySession) -> Path:
    """原子写入会话，避免程序中途退出时留下半份 JSON。"""

    session.folder.mkdir(parents=True, exist_ok=True)
    session.pictures_dir.mkdir(parents=True, exist_ok=True)
    session.updated_at = current_time()
    document = {
        "story_name": session.story_name,
        "session_id": _validate_session_id(session.session_id),
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "messages": messages_to_dict(session.messages),
    }

    temporary_file = session.conversation_file.with_suffix(".json.tmp")
    temporary_file.write_text(
        json.dumps(document, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_file.replace(session.conversation_file)
    return session.conversation_file


def create_story_session(
    story_name: str,
    history_root: Path = HISTORY_DATA_DIR,
) -> StorySession:
    """创建新故事目录、随机会话 ID、JSON 和 pictures 子目录。"""

    display_name = story_name.strip()
    if not display_name:
        raise ValueError("故事名称不能为空。")

    session_id = str(uuid4())
    folder_name = f"{_safe_folder_name(display_name)}__{session_id[:8]}"
    now = current_time()
    session = StorySession(
        story_name=display_name,
        session_id=session_id,
        folder=Path(history_root) / folder_name,
        created_at=now,
        updated_at=now,
    )
    save_story_session(session)
    return session


def load_story_session(story_folder: Path) -> StorySession:
    """从一个故事目录的 conversation.json 恢复元数据和 LangChain 消息。"""

    folder = Path(story_folder)
    conversation_file = folder / CONVERSATION_FILE_NAME
    if not conversation_file.is_file():
        raise FileNotFoundError(f"找不到故事存档：{conversation_file}")

    document = json.loads(conversation_file.read_text(encoding="utf-8"))
    story_name = str(document.get("story_name", "")).strip()
    if not story_name:
        raise ValueError(f"故事存档缺少 story_name：{conversation_file}")

    session_id = _validate_session_id(str(document.get("session_id", "")))
    raw_messages = document.get("messages", [])
    if not isinstance(raw_messages, list):
        raise ValueError(f"messages 必须是列表：{conversation_file}")

    return StorySession(
        story_name=story_name,
        session_id=session_id,
        folder=folder,
        created_at=str(document.get("created_at") or current_time()),
        updated_at=str(document.get("updated_at") or current_time()),
        messages=list(messages_from_dict(raw_messages)),
    )


def list_story_sessions(
    history_root: Path = HISTORY_DATA_DIR,
) -> list[StorySession]:
    """只读取新结构的故事文件夹；忽略 history_data 下散落的旧 JSON。"""

    root = Path(history_root)
    if not root.is_dir():
        return []

    sessions: list[StorySession] = []
    for folder in root.iterdir():
        if not folder.is_dir() or not (folder / CONVERSATION_FILE_NAME).is_file():
            continue
        try:
            sessions.append(load_story_session(folder))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"[跳过损坏的故事存档] {folder.name}：{error}", flush=True)
    return sorted(sessions, key=lambda item: item.updated_at, reverse=True)


def choose_story_session(
    history_root: Path = HISTORY_DATA_DIR,
) -> StorySession:
    """按故事名称展示存档；输入序号恢复，直接回车创建新故事。"""

    sessions = list_story_sessions(history_root)
    if sessions:
        print("现有故事：")
        for index, session in enumerate(sessions, start=1):
            turns = sum(message.type == "human" for message in session.messages)
            print(f"  [{index}] {session.story_name}（{turns} 轮）")
    else:
        print("当前还没有故事存档。")

    while True:
        choice = input("输入故事序号继续，直接回车创建新故事：\n> ").strip()
        if not choice:
            while True:
                story_name = input("请输入新故事名称：\n> ").strip()
                try:
                    return create_story_session(story_name, history_root)
                except ValueError as error:
                    print(error, flush=True)
        if choice.isdigit() and 1 <= int(choice) <= len(sessions):
            return sessions[int(choice) - 1]
        print("请输入列表中的故事序号，或直接回车创建新故事。", flush=True)
