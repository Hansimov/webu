from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from webu.llms.client import LLMClient


def _mock_response(status_code=200, payload=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload or {
        "choices": [{"message": {"content": "ok"}}],
    }
    return response


class TestLLMClientHelpers:
    def test_normalizes_openai_compatible_endpoints(self):
        client = LLMClient(endpoint="http://localhost:27800", api_format="openai")

        assert client.endpoint == "http://localhost:27800/v1/chat/completions"
        assert client.models_endpoint == "http://localhost:27800/v1/models"
        assert client.health_endpoint == "http://localhost:27800/health"

    def test_get_default_model_uses_discovered_models(self):
        client = LLMClient(endpoint="http://localhost:27800", api_format="openai")

        models_response = MagicMock()
        models_response.status_code = 200
        models_response.json.return_value = {
            "object": "list",
            "data": [{"id": "qwen3"}],
        }

        with patch("webu.llms.client.requests.get", return_value=models_response):
            assert client.get_default_model() == "qwen3"
            assert client.get_default_model() == "qwen3"

    def test_health_prefers_health_endpoint_payload(self):
        client = LLMClient(endpoint="http://localhost:27800", api_format="openai")

        models_response = MagicMock()
        models_response.status_code = 200
        models_response.json.return_value = {
            "object": "list",
            "data": [{"id": "qwen3"}],
        }

        health_response = MagicMock()
        health_response.status_code = 200
        health_response.json.return_value = {
            "status": "healthy",
            "healthy": 2,
            "total": 2,
        }

        with patch(
            "webu.llms.client.requests.get",
            side_effect=[models_response, health_response],
        ):
            health = client.health()

        assert health["ok"] is True
        assert health["models"] == ["qwen3"]
        assert health["healthy"] == 2
        assert health["health_endpoint"] == "http://localhost:27800/health"

    def test_is_healthy_falls_back_to_models_when_health_unavailable(self):
        client = LLMClient(endpoint="http://localhost:27800", api_format="openai")

        models_response = MagicMock()
        models_response.status_code = 200
        models_response.json.return_value = {
            "object": "list",
            "data": [{"id": "qwen3"}],
        }

        health_response = MagicMock()
        health_response.status_code = 503

        with patch(
            "webu.llms.client.requests.get",
            side_effect=[models_response, health_response],
        ):
            assert client.is_healthy() is True

    def test_deepseek_thinking_payload_uses_v4_params(self):
        client = LLMClient(
            endpoint="https://api.deepseek.com",
            api_format="deepseek",
            model="deepseek-v4-pro",
        )
        response = _mock_response()

        with patch("webu.llms.client.requests.post", return_value=response) as post:
            client.create_response(
                messages=[{"role": "user", "content": "hello"}],
                enable_thinking=True,
                temperature=0.7,
                extra_body={"reasoning_effort": "max", "tool_choice": "auto"},
                stream=False,
            )

        payload = post.call_args.kwargs["json"]
        assert payload["model"] == "deepseek-v4-pro"
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == "max"
        assert "tool_choice" not in payload
        assert "temperature" not in payload
        assert "enable_thinking" not in payload

    def test_deepseek_legacy_reasoner_maps_to_v4_flash_thinking(self):
        client = LLMClient(
            endpoint="https://api.deepseek.com",
            api_format="deepseek",
            model="deepseek-reasoner",
        )
        response = _mock_response()

        with patch("webu.llms.client.requests.post", return_value=response) as post:
            client.create_response(
                messages=[{"role": "user", "content": "hello"}],
                stream=False,
            )

        payload = post.call_args.kwargs["json"]
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == "high"

    def test_deepseek_messages_replay_reasoning_content_without_think_tags(self):
        messages = [
            {
                "role": "assistant",
                "content": "<think>分析工具结果</think>\n最终回答",
                "tool_calls": [{"id": "call_1", "type": "function"}],
            },
            {"role": "developer", "content": "rules"},
        ]

        normalized = LLMClient._normalize_deepseek_messages(messages)

        assert normalized[0]["content"] == "最终回答"
        assert normalized[0]["reasoning_content"] == "分析工具结果"
        assert normalized[0]["tool_calls"] == [{"id": "call_1", "type": "function"}]
        assert normalized[1]["role"] == "system"

    def test_json_response_preserves_deepseek_reasoning_when_content_empty(self):
        client = LLMClient(endpoint="https://api.deepseek.com", api_format="deepseek")
        response = _mock_response(
            payload={
                "choices": [
                    {
                        "message": {
                            "reasoning_content": "这里包含可展示内容",
                            "content": "",
                        }
                    }
                ],
                "usage": {"total_tokens": 3},
            }
        )

        text, usage = client.parse_json_response(response)

        assert text == "<think>这里包含可展示内容</think>"
        assert usage == {"total_tokens": 3}

    def test_stream_response_skips_sse_comments_and_splits_reasoning(self):
        client = LLMClient(endpoint="https://api.deepseek.com", api_format="deepseek")
        response = MagicMock()
        lines = [
            ": keep-alive",
            'data: {"choices":[{"delta":{"reasoning_content":"先分析"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":"再回答"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":4}}',
            "data: [DONE]",
        ]
        response.iter_lines.return_value = iter(
            [
                line.encode("utf-8")
                for line in lines
            ]
        )

        text, usage = client.parse_stream_response(response)

        assert text == "<think>先分析</think>再回答"
        assert usage == {"total_tokens": 4}
