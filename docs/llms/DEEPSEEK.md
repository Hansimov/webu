# DeepSeek V4 Client Notes

`webu.llms.client.LLMClient` treats DeepSeek V4 as an OpenAI-compatible Chat
Completions provider with provider-specific thinking semantics.

## Request Shape

- Use `model=deepseek-v4-flash` or `model=deepseek-v4-pro`.
- Thinking is controlled by request parameters, not by a separate model ID:
  `thinking={"type": "enabled"}` plus `reasoning_effort`.
- The default adapter uses `reasoning_effort="high"` when thinking is enabled.
  Callers can override it with `extra_body={"reasoning_effort": "max"}`.
- Thinking mode removes sampling parameters that DeepSeek documents as
  unsupported for reasoning responses.
- Legacy `deepseek-chat` and `deepseek-reasoner` are normalized to
  `deepseek-v4-flash` non-thinking/thinking respectively.

## Response Parsing

DeepSeek returns reasoning and visible answer separately:

- non-streaming: `choices[0].message.reasoning_content` and
  `choices[0].message.content`
- streaming: `choices[0].delta.reasoning_content` and
  `choices[0].delta.content`

The client keeps this split internally and returns the combined string as
`<think>...</think>answer` for existing call sites. If DeepSeek returns an empty
`content` with useful text in `reasoning_content`, the reasoning block is still
preserved instead of being dropped.

## Message History

DeepSeek V4 thinking mode may require `reasoning_content` to be replayed across
tool-call turns. To avoid leaking `<think>` tags back as normal assistant text,
assistant messages shaped as `<think>reasoning</think>answer` are normalized to:

```json
{
  "role": "assistant",
  "reasoning_content": "reasoning",
  "content": "answer"
}
```

`developer` role messages are sent as `system`, because DeepSeek's OpenAI-style
endpoint does not advertise developer-role support.

References:

- https://api-docs.deepseek.com/news/news260424
- https://api-docs.deepseek.com/guides/thinking_mode
- https://api-docs.deepseek.com/guides/reasoning_model
- https://api-docs.deepseek.com/quick_start/agent_integrations/oh_my_pi
