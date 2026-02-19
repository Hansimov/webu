import json

from pathlib import Path
from tclogger import logger, logstr, dict_to_str, norm_path
from typing import TypedDict, Optional

from .constants import (
    GEMINI_URL,
    GEMINI_BROWSER_PORT,
    GEMINI_API_PORT,
    GEMINI_VNC_PORT,
    GEMINI_NOVNC_PORT,
    GEMINI_USER_DATA_DIR,
    GEMINI_DEFAULT_PROXY,
    GEMINI_CONFIG_FILE,
    GEMINI_CHROME_EXECUTABLE,
    GEMINI_PAGE_LOAD_TIMEOUT,
    GEMINI_RESPONSE_TIMEOUT,
    GEMINI_IMAGE_GENERATION_TIMEOUT,
)


class GeminiConfigType(TypedDict):
    proxy: Optional[str]
    browser_port: Optional[int]
    api_port: Optional[int]
    vnc_port: Optional[int]
    novnc_port: Optional[int]
    user_data_dir: Optional[str]
    chrome_executable: Optional[str]
    headless: Optional[bool]
    page_load_timeout: Optional[int]
    response_timeout: Optional[int]
    image_generation_timeout: Optional[int]
    verbose: Optional[bool]


DEFAULT_GEMINI_CONFIG: GeminiConfigType = {
    "proxy": GEMINI_DEFAULT_PROXY,
    "browser_port": GEMINI_BROWSER_PORT,
    "api_port": GEMINI_API_PORT,
    "vnc_port": GEMINI_VNC_PORT,
    "novnc_port": GEMINI_NOVNC_PORT,
    "user_data_dir": GEMINI_USER_DATA_DIR,
    "chrome_executable": GEMINI_CHROME_EXECUTABLE,
    "headless": False,
    "page_load_timeout": GEMINI_PAGE_LOAD_TIMEOUT,
    "response_timeout": GEMINI_RESPONSE_TIMEOUT,
    "image_generation_timeout": GEMINI_IMAGE_GENERATION_TIMEOUT,
    "verbose": False,
}


class GeminiConfig:
    """Gemini 模块配置管理器。

    优先级：默认配置 < 配置文件 < 输入配置
    """

    def __init__(self, config: GeminiConfigType = None, config_path: str = None):
        self.config_path = norm_path(config_path or GEMINI_CONFIG_FILE)
        self.config: GeminiConfigType = {**DEFAULT_GEMINI_CONFIG}
        self._load_from_file()
        if config:
            self.config.update({k: v for k, v in config.items() if v is not None})

    def _load_from_file(self):
        """从 JSON 文件加载配置（如果文件存在）。"""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                self.config.update(
                    {k: v for k, v in file_config.items() if v is not None}
                )
                logger.mesg(
                    f"  Loaded config from: {logstr.file(str(self.config_path))}"
                )
            except Exception as e:
                logger.warn(f"  × Failed to load config: {e}")

    def save_to_file(self):
        """将当前配置保存到 JSON 文件。"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
        logger.okay(f"  + Config saved to: {logstr.file(str(self.config_path))}")

    @staticmethod
    def create_default_config(config_path: str = None):
        """创建默认配置文件。"""
        cfg = GeminiConfig(config_path=config_path)
        cfg.save_to_file()
        return cfg

    @property
    def proxy(self) -> str:
        return self.config.get("proxy", GEMINI_DEFAULT_PROXY)

    @property
    def browser_port(self) -> int:
        return self.config.get("browser_port", GEMINI_BROWSER_PORT)

    @property
    def api_port(self) -> int:
        return self.config.get("api_port", GEMINI_API_PORT)

    @property
    def vnc_port(self) -> int:
        return self.config.get("vnc_port", GEMINI_VNC_PORT)

    @property
    def novnc_port(self) -> int:
        return self.config.get("novnc_port", GEMINI_NOVNC_PORT)

    @property
    def user_data_dir(self) -> str:
        return self.config.get("user_data_dir", GEMINI_USER_DATA_DIR)

    @property
    def chrome_executable(self) -> str:
        return self.config.get("chrome_executable", GEMINI_CHROME_EXECUTABLE)

    @property
    def headless(self) -> bool:
        return self.config.get("headless", False)

    @property
    def page_load_timeout(self) -> int:
        return self.config.get("page_load_timeout", GEMINI_PAGE_LOAD_TIMEOUT)

    @property
    def response_timeout(self) -> int:
        return self.config.get("response_timeout", GEMINI_RESPONSE_TIMEOUT)

    @property
    def image_generation_timeout(self) -> int:
        return self.config.get(
            "image_generation_timeout", GEMINI_IMAGE_GENERATION_TIMEOUT
        )

    @property
    def verbose(self) -> bool:
        return self.config.get("verbose", False)

    def log_config(self):
        """输出当前配置（用于调试）。"""
        safe_config = {**self.config}
        logger.note("> Gemini Config:")
        logger.mesg(dict_to_str(safe_config), indent=2)

    def __repr__(self):
        return f"GeminiConfig({self.config})"
