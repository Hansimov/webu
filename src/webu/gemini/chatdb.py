"""本地聊天数据库：基于 JSON 文件系统的聊天历史管理。

使用 JSON 文件存储聊天数据，支持按聊天 ID 管理不同的聊天记录。
文件引用（如图片路径）保存在 JSON 中的 files 字段中。

存储结构:
    {data_dir}/
    ├── index.json            # 所有聊天的索引（ID、标题、时间、消息数）
    ├── {chat_id_1}.json      # 聊天 1 的完整消息记录
    ├── {chat_id_2}.json      # 聊天 2 的完整消息记录
    └── ...
"""

import json
import os
import uuid

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from tclogger import logger, logstr
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════════════════════


@dataclass
class ChatMessage:
    """单条聊天消息。"""

    role: str  # "user" 或 "model"
    content: str = ""
    timestamp: str = ""
    files: list[str] = field(default_factory=list)  # 关联的文件路径列表

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "files": self.files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatMessage":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            timestamp=data.get("timestamp", ""),
            files=data.get("files", []),
        )


@dataclass
class ChatSession:
    """单个聊天会话。"""

    chat_id: str = ""
    title: str = ""
    created_at: str = ""
    updated_at: str = ""
    messages: list[ChatMessage] = field(default_factory=list)

    def __post_init__(self):
        if not self.chat_id:
            self.chat_id = uuid.uuid4().hex[:16]
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict:
        return {
            "chat_id": self.chat_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [msg.to_dict() for msg in self.messages],
        }

    def summary(self) -> dict:
        """返回不含消息内容的摘要信息。"""
        return {
            "chat_id": self.chat_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatSession":
        messages = [ChatMessage.from_dict(m) for m in data.get("messages", [])]
        return cls(
            chat_id=data.get("chat_id", ""),
            title=data.get("title", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            messages=messages,
        )

    def touch(self):
        """更新 updated_at 时间戳。"""
        self.updated_at = datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════
# 聊天数据库
# ═══════════════════════════════════════════════════════════════


class ChatDatabase:
    """基于本地文件系统的聊天数据库。

    每个聊天会话存储为独立的 JSON 文件，索引文件记录所有会话的摘要。
    支持完整的 CRUD 操作以及按关键字搜索。

    用法:
        db = ChatDatabase("data/gemini/chats")

        # 创建聊天
        chat_id = db.create_chat(title="测试聊天")

        # 添加消息
        db.add_message(chat_id, role="user", content="你好")
        db.add_message(chat_id, role="model", content="你好！有什么可以帮你的？",
                       files=["data/images/img_001.png"])

        # 查询
        chat = db.get_chat(chat_id)
        messages = db.get_messages(chat_id)
        all_chats = db.list_chats()

        # 搜索
        results = db.search_chats("你好")

        # 更新
        db.update_chat_title(chat_id, "新标题")
        db.update_message(chat_id, 0, content="修改后的内容")

        # 删除
        db.delete_message(chat_id, 1)
        db.delete_chat(chat_id)
    """

    INDEX_FILE = "index.json"

    def __init__(self, data_dir: str = "data/gemini/chats"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.data_dir / self.INDEX_FILE
        self._ensure_index()

    # ── 索引管理 ──────────────────────────────────────────────

    def _ensure_index(self):
        """确保索引文件存在。"""
        if not self._index_path.exists():
            self._save_index({"chats": []})

    def _load_index(self) -> dict:
        """加载索引文件。"""
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"chats": []}

    def _save_index(self, index: dict):
        """保存索引文件。"""
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2, ensure_ascii=False)

    def _update_index_entry(self, session: ChatSession):
        """在索引中更新或添加一个聊天条目。"""
        index = self._load_index()
        summary = session.summary()

        # 查找并更新现有条目
        for i, entry in enumerate(index["chats"]):
            if entry["chat_id"] == session.chat_id:
                index["chats"][i] = summary
                self._save_index(index)
                return

        # 新增条目
        index["chats"].append(summary)
        self._save_index(index)

    def _remove_index_entry(self, chat_id: str):
        """从索引中删除一个聊天条目。"""
        index = self._load_index()
        index["chats"] = [
            entry for entry in index["chats"] if entry["chat_id"] != chat_id
        ]
        self._save_index(index)

    # ── 聊天文件管理 ──────────────────────────────────────────

    def _chat_path(self, chat_id: str) -> Path:
        """返回聊天 JSON 文件路径。"""
        return self.data_dir / f"{chat_id}.json"

    def _load_chat(self, chat_id: str) -> Optional[ChatSession]:
        """从文件加载聊天会话。"""
        path = self._chat_path(chat_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ChatSession.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warn(f"  × 加载聊天 {chat_id} 失败: {e}")
            return None

    def _save_chat(self, session: ChatSession):
        """保存聊天会话到文件，并更新索引。"""
        path = self._chat_path(session.chat_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)
        self._update_index_entry(session)

    # ── CRUD: 聊天会话 ───────────────────────────────────────

    def create_chat(self, title: str = "", chat_id: str = None) -> str:
        """创建新的聊天会话。

        Args:
            title: 聊天标题（可选）
            chat_id: 自定义聊天 ID（可选，默认自动生成）

        Returns:
            str: 新聊天的 ID
        """
        session = ChatSession(
            chat_id=chat_id or "",
            title=title,
        )
        self._save_chat(session)
        logger.okay(f"  + 创建聊天: {session.chat_id} ({title or '无标题'})")
        return session.chat_id

    def get_chat(self, chat_id: str) -> Optional[ChatSession]:
        """获取聊天会话的完整数据。

        Args:
            chat_id: 聊天 ID

        Returns:
            ChatSession 或 None（不存在时）
        """
        return self._load_chat(chat_id)

    def list_chats(self) -> list[dict]:
        """列出所有聊天会话的摘要。

        Returns:
            list[dict]: 聊天摘要列表，按更新时间倒序
        """
        index = self._load_index()
        chats = index.get("chats", [])
        # 按更新时间倒序排列
        chats.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return chats

    def delete_chat(self, chat_id: str) -> bool:
        """删除聊天会话。

        Args:
            chat_id: 聊天 ID

        Returns:
            bool: 是否成功删除
        """
        path = self._chat_path(chat_id)
        if not path.exists():
            return False
        path.unlink()
        self._remove_index_entry(chat_id)
        logger.okay(f"  - 删除聊天: {chat_id}")
        return True

    def update_chat_title(self, chat_id: str, title: str) -> bool:
        """更新聊天标题。

        Args:
            chat_id: 聊天 ID
            title: 新标题

        Returns:
            bool: 是否成功更新
        """
        session = self._load_chat(chat_id)
        if not session:
            return False
        session.title = title
        session.touch()
        self._save_chat(session)
        return True

    # ── CRUD: 消息 ────────────────────────────────────────────

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str = "",
        files: list[str] = None,
    ) -> Optional[int]:
        """向聊天中添加一条消息。

        Args:
            chat_id: 聊天 ID
            role: 消息角色（"user" 或 "model"）
            content: 消息内容
            files: 关联文件路径列表

        Returns:
            int: 消息索引（在 messages 列表中的位置），失败返回 None
        """
        session = self._load_chat(chat_id)
        if not session:
            return None

        msg = ChatMessage(
            role=role,
            content=content,
            files=files or [],
        )
        session.messages.append(msg)
        session.touch()
        self._save_chat(session)
        return len(session.messages) - 1

    def get_messages(self, chat_id: str) -> Optional[list[dict]]:
        """获取聊天的所有消息。

        Args:
            chat_id: 聊天 ID

        Returns:
            list[dict]: 消息列表，失败返回 None
        """
        session = self._load_chat(chat_id)
        if not session:
            return None
        return [msg.to_dict() for msg in session.messages]

    def get_message(self, chat_id: str, message_index: int) -> Optional[dict]:
        """获取指定索引的消息。

        Args:
            chat_id: 聊天 ID
            message_index: 消息索引

        Returns:
            dict: 消息数据，失败返回 None
        """
        session = self._load_chat(chat_id)
        if not session:
            return None
        if message_index < 0 or message_index >= len(session.messages):
            return None
        return session.messages[message_index].to_dict()

    def update_message(
        self,
        chat_id: str,
        message_index: int,
        content: str = None,
        files: list[str] = None,
    ) -> bool:
        """更新指定索引的消息。

        Args:
            chat_id: 聊天 ID
            message_index: 消息索引
            content: 新内容（None 则不更新）
            files: 新文件列表（None 则不更新）

        Returns:
            bool: 是否成功更新
        """
        session = self._load_chat(chat_id)
        if not session:
            return False
        if message_index < 0 or message_index >= len(session.messages):
            return False

        msg = session.messages[message_index]
        if content is not None:
            msg.content = content
        if files is not None:
            msg.files = files

        session.touch()
        self._save_chat(session)
        return True

    def delete_message(self, chat_id: str, message_index: int) -> bool:
        """删除指定索引的消息。

        Args:
            chat_id: 聊天 ID
            message_index: 消息索引

        Returns:
            bool: 是否成功删除
        """
        session = self._load_chat(chat_id)
        if not session:
            return False
        if message_index < 0 or message_index >= len(session.messages):
            return False

        session.messages.pop(message_index)
        session.touch()
        self._save_chat(session)
        return True

    # ── 搜索 ──────────────────────────────────────────────────

    def search_chats(self, query: str) -> list[dict]:
        """搜索包含指定关键字的聊天。

        在聊天标题和消息内容中搜索。

        Args:
            query: 搜索关键字

        Returns:
            list[dict]: 匹配的聊天摘要列表
        """
        if not query:
            return self.list_chats()

        query_lower = query.lower()
        results = []
        index = self._load_index()

        for entry in index.get("chats", []):
            chat_id = entry["chat_id"]

            # 标题匹配
            if query_lower in entry.get("title", "").lower():
                results.append(entry)
                continue

            # 消息内容匹配
            session = self._load_chat(chat_id)
            if session:
                for msg in session.messages:
                    if query_lower in msg.content.lower():
                        results.append(entry)
                        break

        return results

    # ── 统计 ──────────────────────────────────────────────────

    def stats(self) -> dict:
        """返回数据库统计信息。"""
        index = self._load_index()
        chats = index.get("chats", [])
        total_messages = sum(c.get("message_count", 0) for c in chats)
        return {
            "chat_count": len(chats),
            "total_messages": total_messages,
            "data_dir": str(self.data_dir),
        }

    def clear_all(self) -> int:
        """清空所有聊天数据。

        Returns:
            int: 删除的聊天数量
        """
        index = self._load_index()
        count = len(index.get("chats", []))

        # 删除所有聊天文件
        for entry in index.get("chats", []):
            path = self._chat_path(entry["chat_id"])
            if path.exists():
                path.unlink()

        # 重置索引
        self._save_index({"chats": []})
        logger.okay(f"  - 已清空 {count} 个聊天")
        return count
