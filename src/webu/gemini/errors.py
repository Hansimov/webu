class GeminiError(Exception):
    """所有 Gemini 相关错误的基类。"""

    def __init__(self, message: str = "", details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self):
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class GeminiLoginRequiredError(GeminiError):
    """用户未登录 Gemini 时抛出。"""

    def __init__(
        self,
        message: str = "用户未登录 Gemini，请先手动登录。",
    ):
        super().__init__(message)


class GeminiNetworkError(GeminiError):
    """网络连接失败时抛出（如代理问题）。"""

    def __init__(
        self,
        message: str = "访问 Gemini 时发生网络错误。",
        details: dict = None,
    ):
        super().__init__(message, details)


class GeminiTimeoutError(GeminiError):
    """操作超时时抛出。"""

    def __init__(self, message: str = "操作超时。", timeout_ms: int = None):
        details = {"timeout_ms": timeout_ms} if timeout_ms else {}
        super().__init__(message, details)


class GeminiResponseParseError(GeminiError):
    """无法解析 Gemini 响应时抛出。"""

    def __init__(
        self, message: str = "解析 Gemini 响应失败。", raw_content: str = None
    ):
        details = {"raw_content": raw_content[:500] if raw_content else None}
        super().__init__(message, details)


class GeminiImageGenerationError(GeminiError):
    """图片生成失败时抛出。"""

    def __init__(self, message: str = "图片生成失败。", details: dict = None):
        super().__init__(message, details)


class GeminiBrowserError(GeminiError):
    """浏览器操作失败时抛出。"""

    def __init__(self, message: str = "浏览器操作失败。", details: dict = None):
        super().__init__(message, details)


class GeminiPageError(GeminiError):
    """页面交互失败时抛出。"""

    def __init__(self, message: str = "页面交互失败。", details: dict = None):
        super().__init__(message, details)


class GeminiRateLimitError(GeminiError):
    """触发速率限制时抛出。"""

    def __init__(self, message: str = "已达到 Gemini 速率限制。", details: dict = None):
        super().__init__(message, details)


class GeminiServerRollbackError(GeminiError):
    """Gemini 服务器处理失败后页面回退到初始状态时抛出。

    这种情况发生在消息成功提交后，Gemini 后端因网络或服务器原因
    处理失败，页面自动回退到发送前的状态（输入框中仍有文本，
    欢迎页面重新显示）。可通过重试恢复。
    """

    def __init__(
        self,
        message: str = "Gemini 服务器处理失败，页面已回退。",
        details: dict = None,
    ):
        super().__init__(message, details)


class GeminiImageDownloadError(GeminiError):
    """图片下载失败时抛出。"""

    def __init__(self, message: str = "图片下载失败。", details: dict = None):
        super().__init__(message, details)
