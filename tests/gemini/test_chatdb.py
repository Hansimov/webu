"""聊天数据库 (ChatDatabase) 单元测试。

测试覆盖：
- ChatMessage / ChatSession 数据模型
- ChatDatabase 的完整 CRUD 操作
- 索引管理
- 搜索功能
- 边界情况和错误处理
"""

import json
import pytest
import tempfile
import time

from pathlib import Path

from webu.gemini.chatdb import ChatDatabase, ChatSession, ChatMessage


# ═══════════════════════════════════════════════════════════════════
# 数据模型测试
# ═══════════════════════════════════════════════════════════════════


class TestChatMessage:
    """ChatMessage 数据模型测试。"""

    def test_default_creation(self):
        msg = ChatMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.timestamp != ""  # 应自动设置
        assert msg.files == []

    def test_with_files(self):
        msg = ChatMessage(
            role="model",
            content="图片已生成",
            files=["data/img_1.png", "data/img_2.png"],
        )
        assert msg.role == "model"
        assert len(msg.files) == 2

    def test_to_dict(self):
        msg = ChatMessage(role="user", content="test", files=["a.png"])
        d = msg.to_dict()
        assert d["role"] == "user"
        assert d["content"] == "test"
        assert d["files"] == ["a.png"]
        assert "timestamp" in d

    def test_from_dict(self):
        data = {
            "role": "model",
            "content": "response text",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "files": ["img.png"],
        }
        msg = ChatMessage.from_dict(data)
        assert msg.role == "model"
        assert msg.content == "response text"
        assert msg.timestamp == "2025-01-01T00:00:00+00:00"
        assert msg.files == ["img.png"]

    def test_from_dict_defaults(self):
        msg = ChatMessage.from_dict({})
        assert msg.role == "user"
        assert msg.content == ""
        assert msg.files == []

    def test_roundtrip(self):
        msg = ChatMessage(role="user", content="hello world", files=["f.txt"])
        restored = ChatMessage.from_dict(msg.to_dict())
        assert restored.role == msg.role
        assert restored.content == msg.content
        assert restored.files == msg.files
        assert restored.timestamp == msg.timestamp


class TestChatSession:
    """ChatSession 数据模型测试。"""

    def test_default_creation(self):
        session = ChatSession()
        assert len(session.chat_id) == 16  # 自动生成 16 位 hex
        assert session.title == ""
        assert session.created_at != ""
        assert session.updated_at != ""
        assert session.messages == []

    def test_custom_id(self):
        session = ChatSession(chat_id="my_custom_id", title="Test Chat")
        assert session.chat_id == "my_custom_id"
        assert session.title == "Test Chat"

    def test_to_dict(self):
        session = ChatSession(chat_id="abc", title="Test")
        session.messages.append(ChatMessage(role="user", content="hi"))
        d = session.to_dict()
        assert d["chat_id"] == "abc"
        assert d["title"] == "Test"
        assert len(d["messages"]) == 1
        assert d["messages"][0]["content"] == "hi"

    def test_summary(self):
        session = ChatSession(chat_id="xyz", title="Summary Test")
        session.messages = [
            ChatMessage(role="user", content="a"),
            ChatMessage(role="model", content="b"),
        ]
        s = session.summary()
        assert s["chat_id"] == "xyz"
        assert s["title"] == "Summary Test"
        assert s["message_count"] == 2
        assert "messages" not in s  # 摘要不含消息

    def test_from_dict(self):
        data = {
            "chat_id": "id1",
            "title": "My Chat",
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-02T00:00:00",
            "messages": [
                {"role": "user", "content": "hello"},
                {"role": "model", "content": "hi there", "files": ["img.png"]},
            ],
        }
        session = ChatSession.from_dict(data)
        assert session.chat_id == "id1"
        assert session.title == "My Chat"
        assert len(session.messages) == 2
        assert session.messages[1].files == ["img.png"]

    def test_touch(self):
        session = ChatSession(chat_id="test")
        old_updated = session.updated_at
        time.sleep(0.01)
        session.touch()
        assert session.updated_at >= old_updated

    def test_roundtrip(self):
        session = ChatSession(chat_id="rt", title="Roundtrip")
        session.messages = [
            ChatMessage(role="user", content="q"),
            ChatMessage(role="model", content="a", files=["f.png"]),
        ]
        restored = ChatSession.from_dict(session.to_dict())
        assert restored.chat_id == session.chat_id
        assert restored.title == session.title
        assert len(restored.messages) == 2
        assert restored.messages[1].files == ["f.png"]


# ═══════════════════════════════════════════════════════════════════
# ChatDatabase 测试
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def db(tmp_path):
    """创建临时目录中的 ChatDatabase 实例。"""
    return ChatDatabase(data_dir=str(tmp_path / "chats"))


class TestChatDatabaseCreate:
    """测试聊天创建。"""

    def test_create_chat(self, db):
        chat_id = db.create_chat(title="测试聊天")
        assert chat_id is not None
        assert len(chat_id) > 0

    def test_create_chat_with_custom_id(self, db):
        chat_id = db.create_chat(title="Custom", chat_id="my_id")
        assert chat_id == "my_id"

    def test_create_multiple_chats(self, db):
        id1 = db.create_chat(title="Chat 1")
        id2 = db.create_chat(title="Chat 2")
        id3 = db.create_chat(title="Chat 3")
        assert id1 != id2 != id3

    def test_create_chat_no_title(self, db):
        chat_id = db.create_chat()
        session = db.get_chat(chat_id)
        assert session is not None
        assert session.title == ""


class TestChatDatabaseGet:
    """测试聊天查询。"""

    def test_get_existing_chat(self, db):
        chat_id = db.create_chat(title="Test")
        session = db.get_chat(chat_id)
        assert session is not None
        assert session.chat_id == chat_id
        assert session.title == "Test"

    def test_get_nonexistent_chat(self, db):
        session = db.get_chat("nonexistent_id")
        assert session is None

    def test_list_chats_empty(self, db):
        chats = db.list_chats()
        assert chats == []

    def test_list_chats(self, db):
        db.create_chat(title="First")
        db.create_chat(title="Second")
        chats = db.list_chats()
        assert len(chats) == 2

    def test_list_chats_ordered_by_updated(self, db):
        id1 = db.create_chat(title="Old")
        time.sleep(0.01)
        id2 = db.create_chat(title="New")
        chats = db.list_chats()
        # 最新更新的在前
        assert chats[0]["title"] == "New"
        assert chats[1]["title"] == "Old"


class TestChatDatabaseDelete:
    """测试聊天删除。"""

    def test_delete_existing(self, db):
        chat_id = db.create_chat(title="To Delete")
        assert db.delete_chat(chat_id) is True
        assert db.get_chat(chat_id) is None

    def test_delete_nonexistent(self, db):
        assert db.delete_chat("nonexistent") is False

    def test_delete_updates_index(self, db):
        id1 = db.create_chat(title="Keep")
        id2 = db.create_chat(title="Delete")
        db.delete_chat(id2)
        chats = db.list_chats()
        assert len(chats) == 1
        assert chats[0]["chat_id"] == id1

    def test_delete_all_then_list(self, db):
        id1 = db.create_chat()
        id2 = db.create_chat()
        db.delete_chat(id1)
        db.delete_chat(id2)
        assert db.list_chats() == []


class TestChatDatabaseUpdateTitle:
    """测试更新聊天标题。"""

    def test_update_title(self, db):
        chat_id = db.create_chat(title="Old Title")
        ok = db.update_chat_title(chat_id, "New Title")
        assert ok is True
        session = db.get_chat(chat_id)
        assert session.title == "New Title"

    def test_update_title_nonexistent(self, db):
        ok = db.update_chat_title("nonexistent", "Title")
        assert ok is False


class TestChatDatabaseMessages:
    """测试消息 CRUD。"""

    def test_add_message(self, db):
        chat_id = db.create_chat()
        idx = db.add_message(chat_id, role="user", content="Hello!")
        assert idx == 0

    def test_add_multiple_messages(self, db):
        chat_id = db.create_chat()
        idx0 = db.add_message(chat_id, role="user", content="Q1")
        idx1 = db.add_message(chat_id, role="model", content="A1")
        idx2 = db.add_message(chat_id, role="user", content="Q2")
        assert idx0 == 0
        assert idx1 == 1
        assert idx2 == 2

    def test_add_message_with_files(self, db):
        chat_id = db.create_chat()
        db.add_message(
            chat_id,
            role="model",
            content="图片",
            files=["data/img1.png", "data/img2.png"],
        )
        messages = db.get_messages(chat_id)
        assert len(messages) == 1
        assert messages[0]["files"] == ["data/img1.png", "data/img2.png"]

    def test_add_message_to_nonexistent(self, db):
        idx = db.add_message("nonexistent", role="user", content="hi")
        assert idx is None

    def test_get_messages(self, db):
        chat_id = db.create_chat()
        db.add_message(chat_id, role="user", content="Hello")
        db.add_message(chat_id, role="model", content="Hi there")
        messages = db.get_messages(chat_id)
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Hello"
        assert messages[1]["role"] == "model"

    def test_get_messages_nonexistent(self, db):
        assert db.get_messages("nonexistent") is None

    def test_get_single_message(self, db):
        chat_id = db.create_chat()
        db.add_message(chat_id, role="user", content="Q")
        db.add_message(chat_id, role="model", content="A")
        msg = db.get_message(chat_id, 1)
        assert msg is not None
        assert msg["content"] == "A"

    def test_get_message_out_of_range(self, db):
        chat_id = db.create_chat()
        db.add_message(chat_id, role="user", content="Q")
        assert db.get_message(chat_id, 5) is None
        assert db.get_message(chat_id, -1) is None

    def test_update_message_content(self, db):
        chat_id = db.create_chat()
        db.add_message(chat_id, role="user", content="original")
        ok = db.update_message(chat_id, 0, content="updated")
        assert ok is True
        msg = db.get_message(chat_id, 0)
        assert msg["content"] == "updated"

    def test_update_message_files(self, db):
        chat_id = db.create_chat()
        db.add_message(chat_id, role="model", content="text")
        ok = db.update_message(chat_id, 0, files=["new_file.png"])
        assert ok is True
        msg = db.get_message(chat_id, 0)
        assert msg["files"] == ["new_file.png"]

    def test_update_message_partial(self, db):
        """只更新 content 不影响 files。"""
        chat_id = db.create_chat()
        db.add_message(chat_id, role="model", content="old", files=["f.png"])
        db.update_message(chat_id, 0, content="new")
        msg = db.get_message(chat_id, 0)
        assert msg["content"] == "new"
        assert msg["files"] == ["f.png"]  # 文件未变

    def test_update_message_nonexistent(self, db):
        chat_id = db.create_chat()
        assert db.update_message(chat_id, 0, content="x") is False
        assert db.update_message("bad_id", 0, content="x") is False

    def test_delete_message(self, db):
        chat_id = db.create_chat()
        db.add_message(chat_id, role="user", content="A")
        db.add_message(chat_id, role="model", content="B")
        db.add_message(chat_id, role="user", content="C")
        ok = db.delete_message(chat_id, 1)
        assert ok is True
        messages = db.get_messages(chat_id)
        assert len(messages) == 2
        assert messages[0]["content"] == "A"
        assert messages[1]["content"] == "C"

    def test_delete_message_out_of_range(self, db):
        chat_id = db.create_chat()
        db.add_message(chat_id, role="user", content="A")
        assert db.delete_message(chat_id, 5) is False

    def test_delete_message_nonexistent_chat(self, db):
        assert db.delete_message("bad", 0) is False


class TestChatDatabaseSearch:
    """测试搜索功能。"""

    def test_search_by_title(self, db):
        db.create_chat(title="Python 教程")
        db.create_chat(title="JavaScript 入门")
        results = db.search_chats("Python")
        assert len(results) == 1
        assert results[0]["title"] == "Python 教程"

    def test_search_by_content(self, db):
        id1 = db.create_chat(title="Chat A")
        id2 = db.create_chat(title="Chat B")
        db.add_message(id1, role="user", content="量子计算是什么？")
        db.add_message(id2, role="user", content="Web 开发入门")
        results = db.search_chats("量子")
        assert len(results) == 1
        assert results[0]["chat_id"] == id1

    def test_search_case_insensitive(self, db):
        id1 = db.create_chat(title="Machine Learning")
        results = db.search_chats("machine")
        assert len(results) == 1

    def test_search_no_results(self, db):
        db.create_chat(title="Chat")
        results = db.search_chats("nonexistent_keyword_xyz")
        assert results == []

    def test_search_empty_query(self, db):
        db.create_chat(title="A")
        db.create_chat(title="B")
        results = db.search_chats("")
        assert len(results) == 2  # 返回所有


class TestChatDatabaseStats:
    """测试统计功能。"""

    def test_stats_empty(self, db):
        stats = db.stats()
        assert stats["chat_count"] == 0
        assert stats["total_messages"] == 0

    def test_stats_with_data(self, db):
        id1 = db.create_chat()
        id2 = db.create_chat()
        db.add_message(id1, role="user", content="a")
        db.add_message(id1, role="model", content="b")
        db.add_message(id2, role="user", content="c")
        stats = db.stats()
        assert stats["chat_count"] == 2
        assert stats["total_messages"] == 3


class TestChatDatabaseClearAll:
    """测试全部清空功能。"""

    def test_clear_all(self, db):
        db.create_chat(title="A")
        db.create_chat(title="B")
        db.create_chat(title="C")
        count = db.clear_all()
        assert count == 3
        assert db.list_chats() == []
        assert db.stats()["chat_count"] == 0

    def test_clear_all_empty(self, db):
        count = db.clear_all()
        assert count == 0


class TestChatDatabasePersistence:
    """测试持久化（重新加载后数据是否保持）。"""

    def test_persistence(self, tmp_path):
        data_dir = str(tmp_path / "persist_test")

        # 第一个实例写入数据
        db1 = ChatDatabase(data_dir=data_dir)
        chat_id = db1.create_chat(title="Persistent Chat")
        db1.add_message(chat_id, role="user", content="Remember me")

        # 第二个实例读取数据
        db2 = ChatDatabase(data_dir=data_dir)
        session = db2.get_chat(chat_id)
        assert session is not None
        assert session.title == "Persistent Chat"
        assert len(session.messages) == 1
        assert session.messages[0].content == "Remember me"

    def test_index_persistence(self, tmp_path):
        data_dir = str(tmp_path / "index_test")

        db1 = ChatDatabase(data_dir=data_dir)
        db1.create_chat(title="A")
        db1.create_chat(title="B")

        db2 = ChatDatabase(data_dir=data_dir)
        chats = db2.list_chats()
        assert len(chats) == 2


class TestChatDatabaseEdgeCases:
    """边界情况测试。"""

    def test_empty_content(self, db):
        chat_id = db.create_chat()
        idx = db.add_message(chat_id, role="user", content="")
        assert idx == 0
        msg = db.get_message(chat_id, 0)
        assert msg["content"] == ""

    def test_unicode_content(self, db):
        chat_id = db.create_chat(title="中文聊天 🎉")
        db.add_message(chat_id, role="user", content="こんにちは世界 🌍")
        msg = db.get_message(chat_id, 0)
        assert msg["content"] == "こんにちは世界 🌍"

    def test_large_content(self, db):
        chat_id = db.create_chat()
        large_text = "x" * 100000
        db.add_message(chat_id, role="user", content=large_text)
        msg = db.get_message(chat_id, 0)
        assert len(msg["content"]) == 100000

    def test_many_messages(self, db):
        chat_id = db.create_chat()
        for i in range(100):
            db.add_message(
                chat_id, role="user" if i % 2 == 0 else "model", content=f"Message {i}"
            )
        messages = db.get_messages(chat_id)
        assert len(messages) == 100

    def test_concurrent_index_access(self, db):
        """多次操作后索引应保持一致。"""
        ids = []
        for i in range(10):
            ids.append(db.create_chat(title=f"Chat {i}"))

        # 删除偶数
        for i in range(0, 10, 2):
            db.delete_chat(ids[i])

        chats = db.list_chats()
        assert len(chats) == 5

    def test_data_dir_auto_creation(self, tmp_path):
        deep_path = str(tmp_path / "a" / "b" / "c" / "chats")
        db = ChatDatabase(data_dir=deep_path)
        assert Path(deep_path).exists()
        chat_id = db.create_chat(title="Deep")
        assert db.get_chat(chat_id) is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
