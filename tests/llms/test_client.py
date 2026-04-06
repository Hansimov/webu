from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from webu.llms.client import LLMClient


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
