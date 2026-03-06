from webu.runtime_settings import resolve_gemini_default_proxy

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
GEMINI_DEFAULT_PROXY = resolve_gemini_default_proxy()

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

# 重试配置
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_DELAY = 1.0  # 秒

# ═══════════════════════════════════════════════════════════════
# Gemini 页面元素的 CSS 选择器
# 每组选择器按优先级排列，用逗号分隔作为 CSS 选择器组
# ═══════════════════════════════════════════════════════════════

# ── 登录状态检测 ─────────────────────────────────────────────
# Google Bar 头像和 PRO 徽章（已登录时可见）
SEL_LOGIN_AVATAR = (
    "img.gb_q, "  # Google Bar 标准头像
    'img[data-src*="googleusercontent"], '  # Google 头像 CDN
    'a[aria-label*="Google Account"], '  # 英文界面
    'a[aria-label*="Google 账号"], '  # 中文界面
    'img[class*="profile-avatar"], '  # 通用头像类名
    'div[class*="avatar"] img'  # 头像容器内的图片
)

# 登录/注册按钮（未登录时可见）
SEL_LOGIN_BUTTON = (
    'a[href*="accounts.google.com/ServiceLogin"], '
    'a[href*="accounts.google.com"][data-action="sign in"], '
    'a[data-action="sign in"], '
    'button[data-action="sign in"]'
)

# PRO 订阅标识
SEL_PRO_BADGE = (
    '[class*="upgrade-badge"], ' '[class*="pro-badge"], ' '[data-badge="pro"]'
)

# ── 侧边栏 ──────────────────────────────────────────────────
# 侧边栏切换按钮（汉堡菜单图标）
SEL_SIDEBAR_TOGGLE = (
    'button[aria-label*="Main menu"], '
    'button[aria-label*="主菜单"], '
    'button[aria-label*="menu" i], '
    'button[aria-label*="菜单"], '
    'button[mattooltip*="menu" i], '
    'button[mattooltip*="菜单"]'
)

# 新建会话按钮
SEL_NEW_CHAT_BUTTON = (
    'a[aria-label*="发起新对话"], '  # 实际 DOM: <a> 标签
    'a[aria-label*="New chat"], '
    'button[aria-label*="New chat"], '
    'button[aria-label*="发起新对话"]'
)

# ── 聊天输入 ─────────────────────────────────────────────────
# 输入框（Gemini 使用 contenteditable rich text 编辑器）
SEL_INPUT_AREA = (
    'rich-textarea div.ql-editor[contenteditable="true"], '  # Quill 编辑器
    'div.ql-editor[contenteditable="true"], '  # Quill 无 rich-textarea 包裹
    'rich-textarea div[contenteditable="true"], '  # rich-textarea 内
    'div[contenteditable="true"][role="textbox"], '  # 通用 textbox
    'div[contenteditable="true"][aria-label*="prompt" i], '  # 英文
    'div[contenteditable="true"][aria-label*="输入"]'  # 中文
)

# 发送按钮
SEL_SEND_BUTTON = (
    'button[aria-label*="Send" i], '
    'button[aria-label*="发送"], '
    'button[mattooltip*="Send" i], '
    'button[mattooltip*="发送"], '
    "button.send-button, "
    'button[data-test-id="send-button"]'
)

# ── 工具和模型选择 ───────────────────────────────────────────
# 工具按钮（toolbox-drawer 按钮，而非零态意图卡片）
SEL_TOOLS_BUTTON = (
    "button.toolbox-drawer-button, "  # 实际 DOM class
    'button[aria-label="工具"], '  # 精确匹配（避免匹配卡片的 "点按即可使用工具"）
    'button[aria-label="Tools"]'
)

# 图片生成 — 零态卡片 + 工具抽屉
SEL_IMAGE_GEN_OPTION = (
    'button[aria-label*="制作图片"], '  # 零态卡片
    'button[aria-label*="Generate image" i], '  # 英文零态卡片
    'toolbox-drawer button[aria-label*="image" i], '  # 工具抽屉中的选项
    'button[data-test-id="image-generation"], '
    '[role="menuitem"]'
)

# 模型/模式选择器（实际 DOM: button[aria-label="打开模式选择器"] text="快速"）
SEL_MODEL_SELECTOR = (
    'button[aria-label*="模式选择器"], '  # 中文
    'button[aria-label*="mode selector" i], '  # 英文
    "button.input-area-switch, "  # class 名
    'button[aria-label*="model" i], '
    'button[data-test-id="model-selector"], '
    'div[role="listbox"]'
)

# PRO 徽章/按钮（disabled=True 表示已是 PRO 用户）
SEL_PRO_BUTTON = (
    "button.pillbox-btn, "  # 实际 DOM class
    "button.gds-pillbox-button"
)

# ── 响应区域 ─────────────────────────────────────────────────
# 响应容器（包含完整的模型回复）
SEL_RESPONSE_CONTAINER = (
    "message-content, "
    "model-response, "
    ".response-container, "
    ".model-response-text, "
    'div[class*="response-container"], '
    'div[class*="model-response"]'
)

# 响应中的文本区域
SEL_RESPONSE_TEXT = (
    "message-content .markdown, "
    "message-content .markdown-main-panel, "
    ".response-container .markdown, "
    ".model-response-text"
)

# 响应中的图片
SEL_RESPONSE_IMAGES = (
    "message-content img, " ".response-container img, " "model-response img"
)

# 响应中的代码块
SEL_RESPONSE_CODE_BLOCKS = "message-content pre code, " ".response-container pre code"

# ── 加载/流式传输状态 ────────────────────────────────────────
# 加载指示器（Gemini 思考中）
# 注意: 不要包含 div[class*="thinking"]，因为思考模式的响应中
# 有永久的 "thinking" 区域，匹配后会导致 is_loading 一直为 True
SEL_LOADING_INDICATOR = (
    "mat-progress-bar, "
    ".loading-indicator, "
    ".thinking-indicator, "
    '[class*="loading-spinner"], '
    '[class*="progress-bar"]'
)

# 停止生成按钮（流式输出时可见）
SEL_STOP_BUTTON = (
    'button[aria-label*="Stop" i], '
    'button[aria-label*="停止"], '
    'button[mattooltip*="Stop" i], '
    'button[mattooltip*="停止"]'
)

# ── 错误指示器 ───────────────────────────────────────────────
SEL_ERROR_MESSAGE = (
    ".error-message, "
    'div[class*="error-message"], '
    ".snackbar-error, "
    'div[class*="error-container"]'
)

SEL_QUOTA_WARNING = (
    'div[class*="quota"], ' 'div[class*="rate-limit"], ' 'div[class*="limit-warning"]'
)

# ── 文件上传 ─────────────────────────────────────────────────
SEL_FILE_UPLOAD_BUTTON = (
    'button[aria-label*="Upload" i], '
    'button[aria-label*="上传"], '
    'button[aria-label*="添加文件"], '
    'button[aria-label*="Add file" i], '
    'button[aria-label*="附件"], '
    'button[aria-label*="Attach" i], '
    'button[aria-label*="插入文件" i]'
)

SEL_FILE_UPLOAD_INPUT = 'input[type="file"]'

SEL_ATTACHMENT_CHIP = (
    ".attachment-chip, "
    '[class*="attachment-chip"], '
    '[class*="file-chip"], '
    'div[class*="upload-chip"], '
    '[class*="uploaded-file"]'
)

SEL_ATTACHMENT_REMOVE = (
    'button[aria-label*="Remove" i], '
    'button[aria-label*="删除"], '
    'button[aria-label*="移除"], '
    'button[aria-label*="取消"]'
)

# ── 聊天列表（侧边栏）────────────────────────────────────────
SEL_CHAT_LIST_ITEM = (
    'a[class*="conversation"], '
    'a[class*="chat-item"], '
    'nav a[href*="/app/"], '
    'div[class*="conversation-list"] a, '
    'a[class*="nav-link"][href*="/app/"]'
)

# ── 模式选项（下拉菜单中）────────────────────────────────────
# 实际 DOM: <button role="menuitemradio" class="bard-mode-list-button">
SEL_MODE_OPTION = (
    'button[role="menuitemradio"], '  # 实际 DOM role
    "button.bard-mode-list-button, "  # 实际 DOM class
    '[data-test-id^="bard-mode-option"], '  # test-id
    'div[role="option"], '  # 兼容
    "mat-option"
)

# ── 工具选项（工具抽屉菜单中）────────────────────────────────
# 实际 DOM: <button role="menuitemcheckbox" class="toolbox-drawer-item-list-button">
SEL_TOOL_OPTION = (
    'button[role="menuitemcheckbox"], '  # 实际 DOM role
    "button.toolbox-drawer-item-list-button"  # 实际 DOM class
)

# ── 用户消息和模型消息容器 ───────────────────────────────────
SEL_USER_MESSAGE = (
    "user-query, "
    ".user-query, "
    '[class*="user-message"], '
    '[class*="query-content"]'
)

SEL_MODEL_MESSAGE = "model-response, " ".model-response, " '[class*="model-response"]'
