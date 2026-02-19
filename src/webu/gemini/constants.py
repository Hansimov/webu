GEMINI_URL = "https://gemini.google.com/app"
GEMINI_NEW_CHAT_URL = "https://gemini.google.com/app"

# 默认端口（30000+ 以避免冲突）
GEMINI_BROWSER_PORT = 30001
GEMINI_API_PORT = 30002
GEMINI_VNC_PORT = 30003  # Xvnc 原始 VNC 端口
GEMINI_NOVNC_PORT = 30004  # noVNC Web 查看器端口（websockify）

# 默认用户数据目录（独立于其他浏览器实例）
GEMINI_USER_DATA_DIR = "./data/chrome/gemini"

# noVNC Web 查看器目录
GEMINI_NOVNC_DIR = "./data/novnc"

# 默认代理
GEMINI_DEFAULT_PROXY = "http://127.0.0.1:11119"

# 默认配置文件路径
GEMINI_CONFIG_FILE = "configs/gemini.json"

# 浏览器可执行文件 - 默认使用系统 Chrome
GEMINI_CHROME_EXECUTABLE = "/usr/bin/google-chrome"

# 超时时间（毫秒）
GEMINI_PAGE_LOAD_TIMEOUT = 60000
GEMINI_LOGIN_CHECK_TIMEOUT = 15000
GEMINI_RESPONSE_TIMEOUT = 120000
GEMINI_IMAGE_GENERATION_TIMEOUT = 180000
GEMINI_NAVIGATION_TIMEOUT = 30000

# 轮询间隔（毫秒）
GEMINI_POLL_INTERVAL = 500

# Gemini 页面元素的 CSS 选择器
# 登录状态检测
SEL_LOGIN_AVATAR = 'img[class*="profile"], img[data-src*="googleusercontent"], a[aria-label*="Google"], img.gb_q'
SEL_LOGIN_BUTTON = 'a[href*="accounts.google.com"], a[data-action="sign in"]'
SEL_PRO_BADGE = 'span:has-text("PRO"), div:has-text("PRO")'

# 侧边栏
SEL_SIDEBAR_TOGGLE = 'button[aria-label*="menu"], button[aria-label*="菜单"], button[mattooltip*="menu"], button[mattooltip*="菜单"]'
SEL_NEW_CHAT_BUTTON = 'button:has-text("New chat"), button:has-text("发起新对话"), a:has-text("New chat"), a:has-text("发起新对话")'

# 聊天输入
SEL_INPUT_AREA = '.ql-editor[contenteditable="true"], div[contenteditable="true"][role="textbox"], rich-textarea div[contenteditable="true"]'
SEL_SEND_BUTTON = 'button[aria-label*="Send"], button[aria-label*="发送"], button[mattooltip*="Send"], button[mattooltip*="发送"], button.send-button'

# 工具和模型选择
SEL_TOOLS_BUTTON = 'button:has-text("工具"), button:has-text("Tools")'
SEL_IMAGE_GEN_OPTION = 'button:has-text("生成图片"), button:has-text("Generate image"), span:has-text("生成图片"), span:has-text("Generate image")'
SEL_MODEL_SELECTOR = (
    'button:has-text("Pro"), button[aria-label*="model"], div[role="listbox"]'
)

# 响应区域
SEL_RESPONSE_CONTAINER = (
    'message-content, .response-container, .model-response-text, div[class*="response"]'
)
SEL_RESPONSE_TEXT = (
    "message-content .markdown, .response-container .markdown, .model-response-text"
)
SEL_RESPONSE_IMAGES = "message-content img, .response-container img"
SEL_RESPONSE_CODE_BLOCKS = "message-content pre code, .response-container pre code"

# 加载/流式传输指示器
SEL_LOADING_INDICATOR = '.loading-indicator, mat-progress-bar, .thinking-indicator, [class*="loading"], [class*="progress"]'
SEL_STOP_BUTTON = 'button[aria-label*="Stop"], button[aria-label*="停止"]'

# 错误指示器
SEL_ERROR_MESSAGE = '.error-message, div[class*="error"], .snackbar-error'
SEL_QUOTA_WARNING = 'div:has-text("quota"), div:has-text("limit"), div:has-text("配额")'
