import asyncio
import ast
import json
import re
import requests

from copy import deepcopy
from tclogger import logger, logstr, Runtimer
from tclogger import dict_to_str, dt_to_str, obj_param, obj_params
from typing import Literal, TypedDict
from urllib.parse import urlsplit, urlunsplit

LlmApiType = Literal[
    "openai",
    "minimax",
    "qwen_vllm",
    "dashscope",
    "deepseek",
    "doubao",
    "ollama",
]
ThinkingAdapterType = Literal[
    "auto",
    "openai",
    "minimax",
    "qwen_vllm",
    "dashscope",
    "deepseek",
    "doubao",
    "none",
]

OPENAI_COMPATIBLE_API_FORMATS = (
    "openai",
    "minimax",
    "qwen_vllm",
    "dashscope",
    "deepseek",
    "doubao",
)
MINIMAX_MODEL_PATTERN = re.compile(r"\bminimax\b", re.IGNORECASE)
MINIMAX_ENDPOINT_HINT_PATTERN = re.compile(r"minimax", re.IGNORECASE)
QWEN_MODEL_PATTERN = re.compile(r"\b(qwen|qwq)\b", re.IGNORECASE)
DEEPSEEK_MODEL_PATTERN = re.compile(r"\bdeepseek\b", re.IGNORECASE)
DEEPSEEK_LEGACY_MODEL_ALIASES = {
    "deepseek-chat": ("deepseek-v4-flash", False),
    "deepseek-reasoner": ("deepseek-v4-flash", True),
}
CLOUD_VENDOR_ENDPOINT_SUFFIX = "".join(("ali", "yuncs", ".", "com"))
DOUBAO_ENDPOINT_HINT_PATTERN = re.compile(
    r"(volcengine|volces|doubao|ark\.cn)",
    re.IGNORECASE,
)
QWEN_ENDPOINT_HINT_PATTERN = re.compile(
    r"(dashscope|"
    + re.escape(CLOUD_VENDOR_ENDPOINT_SUFFIX)
    + r"|localhost|127\.0\.0\.1|0\.0\.0\.0)",
    re.IGNORECASE,
)
THINKING_PARAM_ERROR_PATTERN = re.compile(
    r"(enable_thinking|chat_template_kwargs|thinking|reasoning_content)",
    re.IGNORECASE,
)
THINKING_TAG_PATTERN = re.compile(r"<\s*/?think(?:ing)?\s*>", re.IGNORECASE)
THINKING_BLOCK_PATTERN = re.compile(
    r"<\s*think(?:ing)?\s*>(.*?)<\s*/\s*think(?:ing)?\s*>",
    re.IGNORECASE | re.DOTALL,
)


class LLMConfigsType(TypedDict):
    endpoint: str
    api_key: str = ""
    model: str = ""
    api_format: LlmApiType = "openai"
    thinking_adapter: ThinkingAdapterType = "auto"
    stream: bool = None
    max_tokens: int = None
    timeout: float = None
    init_messages: list = []
    enable_thinking: bool = None
    delta_func: callable = None
    terminate_event: asyncio.Event = None
    verbose_user: bool = True
    verbose_assistant: bool = True
    verbose_think: bool = True
    verbose_content: bool = True
    verbose_usage: bool = True
    verbose_finish: bool = True
    verbose: bool = False


DEFAULT_CHAT_PARAMS = {
    "model": "",
    "stream": True,
    "temperature": 0.0,
}


def _normalize_chat_endpoint(endpoint: str, api_format: LlmApiType) -> str:
    normalized = endpoint.rstrip("/")
    if api_format not in OPENAI_COMPATIBLE_API_FORMATS:
        return normalized

    parsed = urlsplit(normalized)
    path = parsed.path or ""
    if path.endswith("/v1/chat/completions") or path.endswith("/chat/completions"):
        return normalized
    if path.endswith("/v1"):
        path = f"{path}/chat/completions"
    elif not path:
        path = "/v1/chat/completions"
    else:
        path = f"{path}/v1/chat/completions"

    return urlunsplit(
        (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
    )


def _normalize_models_endpoint(endpoint: str, api_format: LlmApiType) -> str:
    chat_endpoint = _normalize_chat_endpoint(endpoint, api_format)
    if api_format not in OPENAI_COMPATIBLE_API_FORMATS:
        return chat_endpoint.rstrip("/")
    if chat_endpoint.endswith("/chat/completions"):
        return f"{chat_endpoint[: -len('/chat/completions')]}/models"
    return f"{chat_endpoint.rstrip('/')}/models"


def _normalize_health_endpoint(endpoint: str, api_format: LlmApiType) -> str:
    chat_endpoint = _normalize_chat_endpoint(endpoint, api_format)
    if api_format not in OPENAI_COMPATIBLE_API_FORMATS:
        return f"{chat_endpoint.rstrip('/')}/health"
    if chat_endpoint.endswith("/v1/chat/completions"):
        return f"{chat_endpoint[: -len('/v1/chat/completions')]}/health"
    if chat_endpoint.endswith("/chat/completions"):
        return f"{chat_endpoint[: -len('/chat/completions')]}/health"
    return f"{chat_endpoint.rstrip('/')}/health"


def _iter_text_fragments(value):
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_text_fragments(item)
        return
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            yield value["text"]
            return
        content = value.get("content")
        if isinstance(content, (str, list, dict)):
            yield from _iter_text_fragments(content)


def _merge_text_fragments(fragments: list[str]) -> str:
    merged: list[str] = []
    accumulated = ""
    for fragment in fragments:
        text = str(fragment or "")
        if not text:
            continue
        if accumulated and text.startswith(accumulated):
            if merged:
                merged[-1] = text
            else:
                merged.append(text)
            accumulated = text
            continue
        if text == accumulated or (merged and text == merged[-1]):
            continue
        merged.append(text)
        accumulated += text
    return "".join(merged)


def _extract_reasoning_text(data: dict) -> str:
    fragments = []
    for key in (
        "reasoning_content",
        "reasoning",
        "reasoning_text",
        "reasoning_details",
    ):
        for fragment in _iter_text_fragments(data.get(key)):
            if fragment:
                fragments.append(fragment)
    return _merge_text_fragments(fragments)


def _extract_content_text(data: dict) -> str:
    return "".join(
        fragment for fragment in _iter_text_fragments(data.get("content")) if fragment
    )


def _contains_thinking_tags(text: str) -> bool:
    return bool(text and THINKING_TAG_PATTERN.search(text))


def _split_thinking_content(text: str) -> tuple[str, str]:
    content_text = str(text or "")
    if not content_text:
        return "", ""
    reasoning = "".join(
        fragment.strip()
        for fragment in THINKING_BLOCK_PATTERN.findall(content_text)
        if fragment and fragment.strip()
    )
    content = THINKING_BLOCK_PATTERN.sub("", content_text).strip()
    return reasoning, content


def _extract_message_parts(data: dict) -> tuple[str, str]:
    reasoning = _extract_reasoning_text(data)
    content = _extract_content_text(data)
    if _contains_thinking_tags(content):
        inline_reasoning, inline_content = _split_thinking_content(content)
        if inline_reasoning and not reasoning:
            reasoning = inline_reasoning
        content = inline_content
    return reasoning, content


def _normalize_deepseek_messages(messages: list) -> list:
    normalized_messages = deepcopy(messages or [])
    for message in normalized_messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "developer":
            message["role"] = "system"
        if role != "assistant":
            continue

        content = message.get("content")
        if content is None:
            message["content"] = ""
            continue
        if not isinstance(content, str) or not _contains_thinking_tags(content):
            continue

        reasoning, visible_content = _split_thinking_content(content)
        if reasoning and not message.get("reasoning_content"):
            message["reasoning_content"] = reasoning
        message["content"] = visible_content

    return normalized_messages


def _consume_stream_text(
    stream_state: dict[str, str],
    key: str,
    incoming_text: str,
) -> str:
    text = str(incoming_text or "")
    if not text:
        return ""
    accumulated = stream_state.get(key, "")
    if accumulated and text.startswith(accumulated):
        delta = text[len(accumulated) :]
        stream_state[key] = text
        return delta
    stream_state[key] = accumulated + text
    return text


def _normalize_stream_delta(
    delta_data: dict,
    stream_state: dict[str, str],
) -> dict:
    normalized = dict(delta_data or {})
    reasoning_text, content_text = _extract_message_parts(normalized)
    if reasoning_text:
        normalized["reasoning_content"] = _consume_stream_text(
            stream_state,
            "reasoning",
            reasoning_text,
        )
    content_value = normalized.get("content")
    if content_value is not None:
        normalized["content"] = (
            _consume_stream_text(stream_state, "content", content_text)
            if content_text
            else ""
        )
    return normalized


class LLMClient:
    def __init__(
        self,
        endpoint: str,
        api_key: str = "",
        api_format: LlmApiType = "openai",
        thinking_adapter: ThinkingAdapterType = "auto",
        model: str = None,
        stream: bool = None,
        max_tokens: int = None,
        timeout: float = None,
        init_messages: list = [],
        enable_thinking: bool = None,  # used by qwen3 and doubao
        delta_func: callable = None,
        terminate_event: asyncio.Event = None,
        verbose_user: bool = True,
        verbose_assistant: bool = True,
        verbose_content: bool = True,
        verbose_think: bool = True,
        verbose_usage: bool = True,
        verbose_finish: bool = True,
        verbose: bool = False,
    ):
        self.endpoint = _normalize_chat_endpoint(endpoint, api_format)
        self.models_endpoint = _normalize_models_endpoint(endpoint, api_format)
        self.health_endpoint = _normalize_health_endpoint(endpoint, api_format)
        self._cached_models: list[str] | None = None
        self._cached_default_model: str = ""
        self.api_key = api_key or ""
        self.api_format = api_format
        self.thinking_adapter = thinking_adapter
        self.model = model
        self.provider = self._resolve_provider(model=model)
        self.stream = stream
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.init_messages = init_messages
        self.enable_thinking = enable_thinking
        self.delta_func = delta_func
        self.terminate_event = terminate_event

        self.verbose_user = verbose_user
        self.verbose_assistant = verbose_assistant
        self.verbose_content = verbose_content
        self.verbose_think = verbose_think
        self.verbose_usage = verbose_usage
        self.verbose_finish = verbose_finish
        self.verbose = verbose

        self.is_thinking = False

    def _resolve_provider(self, model: str = None) -> LlmApiType:
        normalized_endpoint = self.endpoint.lower()
        normalized_model = (
            model or self.model or getattr(self, "_cached_default_model", "") or ""
        ).lower()
        if self.api_format in (
            "minimax",
            "qwen_vllm",
            "dashscope",
            "deepseek",
            "doubao",
            "ollama",
        ):
            return self.api_format
        if MINIMAX_ENDPOINT_HINT_PATTERN.search(
            normalized_endpoint
        ) or MINIMAX_MODEL_PATTERN.search(normalized_model):
            return "minimax"
        if DOUBAO_ENDPOINT_HINT_PATTERN.search(normalized_endpoint):
            return "doubao"
        if (
            DEEPSEEK_MODEL_PATTERN.search(normalized_model)
            or "deepseek" in normalized_endpoint
        ):
            return "deepseek"
        if (
            "dashscope" in normalized_endpoint
            or CLOUD_VENDOR_ENDPOINT_SUFFIX in normalized_endpoint
        ):
            return "dashscope"
        if QWEN_MODEL_PATTERN.search(
            normalized_model
        ) or QWEN_ENDPOINT_HINT_PATTERN.search(normalized_endpoint):
            return "qwen_vllm"
        return "openai"

    def _apply_provider_defaults(self, payload: dict, model: str = None) -> None:
        if self._resolve_provider(model) == "minimax":
            payload.setdefault("reasoning_split", True)

    def _normalize_deepseek_model(
        self,
        model: str,
        enable_thinking: bool | None,
    ) -> tuple[str, bool | None]:
        if self._resolve_provider(model) != "deepseek":
            return model, enable_thinking
        normalized_model = str(model or "").strip()
        alias = DEEPSEEK_LEGACY_MODEL_ALIASES.get(normalized_model)
        if alias is None:
            return model, enable_thinking
        replacement_model, alias_enable_thinking = alias
        if enable_thinking is None:
            enable_thinking = alias_enable_thinking
        return replacement_model, enable_thinking

    @staticmethod
    def _extract_message_parts(data: dict) -> tuple[str, str]:
        return _extract_message_parts(data)

    @staticmethod
    def _normalize_stream_delta(
        delta_data: dict,
        stream_state: dict[str, str],
    ) -> dict:
        return _normalize_stream_delta(delta_data, stream_state)

    @staticmethod
    def _normalize_deepseek_messages(messages: list) -> list:
        return _normalize_deepseek_messages(messages)

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    def list_models(self, timeout: float = None) -> list[str]:
        if self.api_format not in OPENAI_COMPATIBLE_API_FORMATS:
            if self.model:
                return [self.model]
            return []
        if self._cached_models is not None:
            return list(self._cached_models)

        req_kwargs = {}
        timeout = timeout if timeout is not None else self.timeout
        if timeout is not None:
            req_kwargs["timeout"] = (min(timeout, 30), timeout)

        try:
            response = requests.get(
                self.models_endpoint,
                headers=self._build_headers(),
                **req_kwargs,
            )
            if response.status_code != 200:
                return []
            payload = response.json()
            models = [
                item.get("id", "")
                for item in payload.get("data", [])
                if isinstance(item, dict) and item.get("id")
            ]
            self._cached_models = models
            if models and not self._cached_default_model:
                self._cached_default_model = models[0]
            return list(models)
        except Exception:
            return []

    def get_default_model(self, timeout: float = None) -> str:
        return self._resolve_model(timeout=timeout)

    def health(self, timeout: float = None) -> dict:
        req_kwargs = {}
        timeout = timeout if timeout is not None else self.timeout
        if timeout is not None:
            req_kwargs["timeout"] = (min(timeout, 30), timeout)

        fallback_models = self.list_models(timeout=timeout)
        if self.api_format not in OPENAI_COMPATIBLE_API_FORMATS:
            return {
                "status": "healthy" if fallback_models else "unknown",
                "ok": bool(fallback_models),
                "endpoint": self.endpoint,
                "health_endpoint": self.health_endpoint,
                "models": fallback_models,
            }

        try:
            response = requests.get(
                self.health_endpoint,
                headers=self._build_headers(),
                **req_kwargs,
            )
            if response.status_code == 200:
                try:
                    payload = response.json()
                except Exception:
                    payload = {
                        "status": "healthy",
                        "healthy": 1,
                        "total": 1,
                    }
                if not isinstance(payload, dict):
                    payload = {
                        "status": "healthy",
                        "healthy": 1,
                        "total": 1,
                    }
                models = fallback_models or self.list_models(timeout=timeout)
                payload.setdefault("status", "healthy")
                payload["ok"] = bool(
                    payload.get("healthy", 0)
                    or payload.get("status") == "healthy"
                    or response.status_code < 400
                )
                payload.setdefault("endpoint", self.endpoint)
                payload.setdefault("health_endpoint", self.health_endpoint)
                payload.setdefault("models", models)
                return payload
        except Exception:
            pass

        if fallback_models:
            return {
                "status": "healthy",
                "ok": True,
                "endpoint": self.endpoint,
                "health_endpoint": self.health_endpoint,
                "models": fallback_models,
            }

        return {
            "status": "unhealthy",
            "ok": False,
            "endpoint": self.endpoint,
            "health_endpoint": self.health_endpoint,
            "models": [],
        }

    def is_healthy(self, timeout: float = None) -> bool:
        return bool(self.health(timeout=timeout).get("ok"))

    def _resolve_model(self, model: str = None, timeout: float = None) -> str:
        explicit_model = (model if model is not None else self.model) or ""
        explicit_model = explicit_model.strip()
        if explicit_model:
            return explicit_model
        if self._cached_default_model:
            return self._cached_default_model
        models = self.list_models(timeout=timeout)
        if models:
            self._cached_default_model = models[0]
            return self._cached_default_model
        return ""

    def _infer_thinking_adapter(self, model: str = None) -> ThinkingAdapterType:
        if self.thinking_adapter != "auto":
            return self.thinking_adapter
        provider = self._resolve_provider(model)
        if provider == "ollama":
            return "none"
        if provider in (
            "minimax",
            "qwen_vllm",
            "dashscope",
            "deepseek",
            "doubao",
        ):
            return provider
        return "openai"

    def _candidate_thinking_adapters(
        self, model: str = None
    ) -> list[ThinkingAdapterType]:
        inferred = self._infer_thinking_adapter(model)
        adapters: list[ThinkingAdapterType] = [inferred]
        if (
            self.thinking_adapter == "auto"
            and self.api_format in OPENAI_COMPATIBLE_API_FORMATS
        ):
            adapters.extend(
                [
                    "minimax",
                    "qwen_vllm",
                    "dashscope",
                    "deepseek",
                    "doubao",
                    "openai",
                ]
            )

        deduped: list[ThinkingAdapterType] = []
        for adapter in adapters:
            if adapter not in deduped:
                deduped.append(adapter)
        return deduped

    @staticmethod
    def _apply_thinking_adapter(
        payload: dict,
        enable_thinking: bool,
        adapter: ThinkingAdapterType,
    ) -> None:
        if adapter in ("none", "auto"):
            return
        if adapter == "minimax":
            payload.pop("enable_thinking", None)
            payload.pop("thinking", None)
            payload.setdefault("reasoning_split", True)
            return
        if adapter == "qwen_vllm":
            chat_template_kwargs = payload.get("chat_template_kwargs", {})
            if not isinstance(chat_template_kwargs, dict):
                chat_template_kwargs = {}
            chat_template_kwargs["enable_thinking"] = enable_thinking
            payload["chat_template_kwargs"] = chat_template_kwargs
            payload.pop("thinking", None)
            payload.pop("enable_thinking", None)
            return
        if adapter == "dashscope":
            payload["enable_thinking"] = enable_thinking
            payload.pop("thinking", None)
            return
        if adapter == "deepseek":
            payload["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
            if enable_thinking:
                payload.setdefault("reasoning_effort", "high")
                payload.pop("tool_choice", None)
                for disabled_param in (
                    "temperature",
                    "top_p",
                    "presence_penalty",
                    "frequency_penalty",
                ):
                    payload.pop(disabled_param, None)
            else:
                payload.pop("reasoning_effort", None)
            payload.pop("enable_thinking", None)
            return
        if adapter == "doubao":
            payload["thinking"] = {"type": "enabled" if enable_thinking else "disabled"}
            payload.pop("enable_thinking", None)
            return
        if adapter == "openai":
            payload["enable_thinking"] = enable_thinking

    @staticmethod
    def _is_thinking_parameter_error(response: requests.Response) -> bool:
        if response.status_code not in (400, 404, 422):
            return False
        try:
            payload = response.json()
            error_text = json.dumps(payload, ensure_ascii=False)
        except Exception:
            error_text = response.text
        return bool(THINKING_PARAM_ERROR_PATTERN.search(error_text or ""))

    def set_enable_thinking(self, enable_thinking: bool = None) -> bool:
        if enable_thinking is not None:
            self.enable_thinking = enable_thinking
        return self.enable_thinking

    def set_think_status(self, tag: str = "<think>"):
        if self.enable_thinking is not False and not self.is_thinking:
            self.is_thinking = True
            logger.mesg(tag, end="", verbose=self.verbose_think)

    def reset_think_status(self, tag: str = "</think>"):
        if self.enable_thinking is not False and self.is_thinking:
            self.is_thinking = False
            logger.mesg(tag, end="", verbose=self.verbose_think)

    def create_response(
        self,
        messages: list,
        model: str = None,
        enable_thinking: bool = None,
        temperature: float = None,
        seed: int = None,
        stream: bool = None,
        max_tokens: int = None,
        timeout: float = None,
        extra_body: dict | None = None,
    ):
        headers = self._build_headers()
        model, stream = obj_params(
            self, DEFAULT_CHAT_PARAMS, model=model, stream=stream
        )
        enable_thinking = self.set_enable_thinking(enable_thinking)
        payload = {
            "messages": self.init_messages + messages,
            "stream": stream,
        }
        resolved_model = self._resolve_model(model, timeout=timeout)
        resolved_model, enable_thinking = self._normalize_deepseek_model(
            resolved_model,
            enable_thinking,
        )
        if resolved_model:
            payload["model"] = resolved_model
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        options = {}
        if temperature is not None:
            options["temperature"] = temperature
        if seed is not None:
            options["seed"] = seed
        if self.api_format == "ollama":
            payload["options"] = options
        else:
            payload.update(options)
        if extra_body:
            payload.update(extra_body)
        self.provider = self._resolve_provider(resolved_model)
        if self.provider == "deepseek":
            payload["messages"] = self._normalize_deepseek_messages(
                payload.get("messages") or []
            )
        self._apply_provider_defaults(payload, resolved_model)
        if stream and self.api_format != "ollama":
            stream_options = payload.get("stream_options", {})
            if not isinstance(stream_options, dict):
                stream_options = {}
            stream_options.setdefault("include_usage", True)
            payload["stream_options"] = stream_options
        timeout = timeout if timeout is not None else self.timeout
        req_kwargs = {}
        if timeout is not None:
            # (connect_timeout, read_timeout) — generous read timeout for thinking models
            req_kwargs["timeout"] = (min(timeout, 30), timeout)

        has_explicit_thinking_fields = bool(
            extra_body
            and any(
                key in extra_body
                for key in ("thinking", "enable_thinking", "chat_template_kwargs")
            )
        )
        candidate_adapters: list[ThinkingAdapterType | None] = [None]
        if enable_thinking is not None and not has_explicit_thinking_fields:
            candidate_adapters = self._candidate_thinking_adapters(resolved_model)

        last_response = None
        for adapter in candidate_adapters:
            attempt_payload = deepcopy(payload)
            if adapter is not None and enable_thinking is not None:
                self._apply_thinking_adapter(
                    attempt_payload,
                    enable_thinking=enable_thinking,
                    adapter=adapter,
                )
            response = requests.post(
                self.endpoint,
                headers=headers,
                json=attempt_payload,
                stream=stream,
                **req_kwargs,
            )
            last_response = response
            if not self._is_thinking_parameter_error(response):
                return response
        return last_response

    def exec_delta_func(self, role: str, content: str):
        if self.delta_func:
            delta_func_args = {"role": role, "content": content}
            if asyncio.iscoroutinefunction(self.delta_func):
                asyncio.run(self.delta_func(**delta_func_args))
            else:
                self.delta_func(**delta_func_args)

    def parse_stream_response(self, response: requests.Response) -> tuple[str, dict]:
        response_content = ""
        usage = None
        role = "assistant"
        stream_state = {"reasoning": "", "content": ""}
        for line in response.iter_lines():
            if self.terminate_event and self.terminate_event.is_set():
                break

            line = line.decode("utf-8")
            remove_patterns = [r"^\s*data:\s*", r"^\s*\[DONE\]\s*"]
            for pattern in remove_patterns:
                line = re.sub(pattern, "", line).strip()

            if not line or line.startswith(":"):
                continue

            if line:
                try:
                    line_data = json.loads(line)
                except Exception as e:
                    try:
                        line_data = ast.literal_eval(line)
                    except:
                        logger.warn(f"× Error: {line}")
                        logger.err(e)
                        raise e

                # Handle API error responses in stream
                if "error" in line_data:
                    err_msg = line_data["error"]
                    if isinstance(err_msg, dict):
                        err_msg = err_msg.get("message", str(err_msg))
                    logger.warn(f"× API Error: {err_msg}")
                    break

                chunk_usage = line_data.get("usage")
                if chunk_usage:
                    usage = chunk_usage
                    if not line_data.get("choices"):
                        logger.file(
                            "\n" + dict_to_str(chunk_usage),
                            verbose=self.verbose_usage,
                        )
                        continue

                if self.api_format == "ollama":
                    # https://github.com/ollama/ollama/blob/main/docs/api.md#response-9
                    delta_data = line_data["message"]
                    finish_reason = "stop" if line_data["done"] else None
                else:
                    # https://platform.openai.com/docs/api-reference/chat/streaming
                    choices = line_data.get("choices", [])
                    if not choices:
                        continue
                    delta_data = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason", None)
                delta_data = self._normalize_stream_delta(delta_data, stream_state)
                if "role" in delta_data:
                    role = delta_data["role"]

                delta_reasoning_content = str(delta_data.get("reasoning_content") or "")
                if delta_reasoning_content:
                    if not self.is_thinking:
                        response_content += "<think>"
                    self.set_think_status()
                    response_content += delta_reasoning_content
                    logger.mesg(
                        delta_reasoning_content, end="", verbose=self.verbose_content
                    )

                delta_content = _extract_content_text(
                    {"content": delta_data.get("content")}
                )
                if delta_content:
                    if self.is_thinking:
                        response_content += "</think>"
                        self.reset_think_status()
                    try:
                        response_content += delta_content
                    except Exception as e:
                        logger.warn(delta_data)
                        logger.err(e)
                        raise e
                    logger.mesg(delta_content, end="", verbose=self.verbose_content)
                    self.exec_delta_func(role, delta_content)
                elif self.is_thinking and not delta_reasoning_content:
                    if finish_reason is not None:
                        if self.is_thinking:
                            response_content += "</think>"
                            self.reset_think_status()
                if finish_reason is not None:
                    if chunk_usage:
                        logger.file(
                            "\n" + dict_to_str(usage), verbose=self.verbose_usage
                        )
                    finish_tag = f"\n[Finished: {finish_reason}]"
                    logger.success(finish_tag, end="", verbose=self.verbose_finish)
                    self.exec_delta_func("stop", "")

        # Ensure thinking tag is closed
        if self.is_thinking:
            response_content += "</think>"
            self.reset_think_status()

        return response_content, usage

    def parse_json_response(self, response: requests.Response) -> tuple[str, dict]:
        response_content = ""
        usage = None
        try:
            response_data = response.json()
            response_content = ""
            if self.api_format == "ollama":
                message = response_data["message"]
            else:
                message = response_data["choices"][0]["message"]
            reasoning_content, content = self._extract_message_parts(message)
            if reasoning_content and content and not _contains_thinking_tags(content):
                response_content = f"<think>{reasoning_content}</think>" + content
            elif reasoning_content:
                response_content = f"<think>{reasoning_content}</think>"
            else:
                response_content = content
            if "usage" in response_data:
                usage = response_data["usage"]
                if usage and self.verbose_usage:
                    logger.file("\n" + dict_to_str(usage))
            if self.verbose_content:
                logger.mesg(response_content)
            if self.verbose_finish:
                logger.success("[Finished]", end="")
        except Exception as e:
            logger.warn(f"× Error: {response.text}")
        return response_content, usage

    @staticmethod
    def extract_user_prompt(messages: list) -> str:
        """Extract displayable user prompt from the last message.

        Handles both text-only messages (str content) and
        VLM multimodal messages (list of content parts).
        """
        content = messages[-1]["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            image_count = 0
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        text_parts.append(part["text"])
                    elif part.get("type") == "image_url":
                        image_count += 1
            summary = ""
            if image_count:
                summary += f"[{image_count} image(s)] "
            summary += " ".join(text_parts)
            return summary
        return str(content)

    def chat(
        self,
        messages: list,
        model: str = None,
        enable_thinking: bool = None,
        temperature: float = None,
        seed: int = None,
        stream: bool = None,
        max_tokens: int = None,
        extra_body: dict | None = None,
        verbose: bool = None,
    ) -> str:
        timer = Runtimer(verbose=False)
        timer.start_time()
        model, stream = obj_params(
            self, DEFAULT_CHAT_PARAMS, model=model, stream=stream
        )

        verbose = verbose if verbose is not None else self.verbose
        logger.enter_quiet(not verbose)

        if self.verbose_user:
            try:
                user_prompt = self.extract_user_prompt(messages)
                logger.note(f"USER: {user_prompt}")
            except Exception as e:
                logger.warn(messages)
                logger.err(e)
                raise e

        response = self.create_response(
            messages=messages,
            model=model,
            enable_thinking=enable_thinking,
            temperature=temperature,
            seed=seed,
            stream=stream,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )

        # Check HTTP status before parsing
        if response.status_code != 200:
            try:
                err_body = response.json()
                err_msg = err_body.get("error", {}).get("message", response.text[:500])
            except Exception:
                err_msg = response.text[:500]
            logger.warn(f"× HTTP {response.status_code}: {err_msg}")
            logger.exit_quiet(not verbose)
            return ""

        if self.verbose_assistant:
            logger.mesg("ASSISTANT: ", end="")

        if stream:
            response_content, usage = self.parse_stream_response(response)
        else:
            response_content, usage = self.parse_json_response(response)
        timer.end_time()
        if self.verbose_finish:
            elapsed_time = dt_to_str(
                timer.elapsed_time(), precision=1, str_format="unit"
            )
            resolved_model = self._resolve_model(model)
            model_name_str = "[" + (resolved_model or "auto").split("/")[-1] + "]"
            logger.note(f" ({elapsed_time}) {logstr.file(model_name_str)}")
        else:
            logger.note("", verbose=self.verbose_content)

        logger.exit_quiet(not verbose)
        return response_content


class LLMClientByConfig(LLMClient):
    def __init__(self, configs: LLMConfigsType):
        super().__init__(**configs)
