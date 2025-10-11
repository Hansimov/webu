# remove whole element with these tags
COMMON_REMOVE_TAGS = ["script", "style", "button", "link"]

# keep env tags (not unwrap)
HEADER_TAGS = ["title", "h1", "h2", "h3", "h4", "h5", "h6"]
LIST_TAGS = ["ul", "ol", "li", "dl", "dt", "dd"]
TABLE_TAGS = ["table", "tr", "td", "th"]
PARA_TAGS = ["p", "pre", "code", "math"]
ENV_TAGS = [*HEADER_TAGS, *LIST_TAGS, *TABLE_TAGS, *PARA_TAGS]

# keep group tags (not unwrap)
GROUP_TAGS = ["section", "div", "details"]

# keep format tags (not unwrap)
POS_TAGS = ["sub", "sup"]
FONT_TAGS = ["b", "strong", "em"]
MARK_TAGS = ["a", "i", "u", "s", "strike", "mark", "ins", "del", "cite", "blockquote"]
FORMAT_TAGS = [*POS_TAGS, *FONT_TAGS, *MARK_TAGS]

# keep img tags (not unwrap)
IMG_TAGS = ["img"]

# protect tags (no preprocessing)
PROTECT_TAGS = ["math"]

# protect attrs (skip filtering)
PROTECT_ATTRS = ["id", "role", "data-sncf", "data-rpos"]

# https://developer.mozilla.org/en-US/docs/Web/MathML/Element
MATH_TAGS = "math maction menclose merror mfenced mfrac mi mmultiscripts mn mo mover mpadded mphantom mroot mrow ms mspace msqrt mstyle msub msubsup msup mtable mtd mtext mtr munder munderover semantics".split()

COMMON_REMOVE_CLASSES = [
    "(?<!has)sidebar",
    "(?<!flex-wrap-)footer",
    "related",
    "comment",
    "topbar",
    "offcanvas",
    "navbar",
]
GOOGLE_REMOVE_CLASSES = [
    "searchform",
    "top_nav",
    "botstuff",  # people also search for
    "S6VXfe",  # accessibility help
    "bottomads",  # Ads
    "rQTE8b",  # filters and topics
    "B6fmyf",  # duplicated search result link
]
COM_163_REMOVE_CLASSES = [
    "(post_)((top)|(side)|(recommends)|(crumb)|(statement)|(next)|(jubao))",
    "ntes-.*nav",
    "nav-bottom",
]
WIKIPEDIA_REMOVE_TAGS = [
    "nav",
]
WIKIPEDIA_REMOVE_CLASSES = [
    "(mw-)((jump-link)|(editsection))",
    "language-list",
    "p-lang-btn",
    "(vector-)((header)|(column)|(sticky-pinned)|(dropdown-content)|(page-toolbar)|(body-before-content))",
    "navbox",
    "catlinks",
]
DOC_PYTHON_REMOVE_CLASSES = ["headerlink"]
AZURE_REMOVE_CLASSES = [
    "visually-hidden",
    "unsupported-browser",
    "article-header-page-actions",
    "feedback",
    "ms--additional-resources",
]
WEIBO_REMOVE_CLASSES = [
    "searchapps",
    "pl_right_side",  # 右侧边栏：热搜
    "m-main-nav",  # 左侧边栏：综合/智搜/实时...
    "m-page",  # 第X页
    "ai_rule_layer",  # 微博智搜使用须知
    "menu\ss-fr",  # 帮上头条/投诉/收藏/...
    "card-act",  # 转发/评论
    "(wbpv-)((menu)|(open-layer-button)|(follow-area)|(hidden)|(control-bar))",  # 视频播放控件
]
WEIXIN_REMOVE_CLASSES = [
    "mobile-links__wrp",
    "weui-actionsheet",
    "fixed-translate",
    "markdown_nav_box",
]
ARXIV_ORG_REMOVE_TAGS = [
    "footer",  # "Click here to ..."
]
ARXIV_ORG_REMOVE_CLASSES = [
    "is-sr-only",  # "Skip to main content"
    "support-ack",  # "We gratefully acknowledge ..." + "Donate"
    "help",  # "Help" + "Advanced Search"
    "labstabs",  # "Bibiographic Tools" + ...
    # "extra-services", # "Access Paper" + ...
    "abs-license",  # "view license"
    "browse",  # "Current browse context"
    "dblp",  # "DBLP - CS Bibliography"
    "extra-ref-cite",  # "export BibTeX citation"
    "extra-general",  # "what is this"
    "bib-cite-modal",  # "BibTeX formatted citation"
    "bookmarks",  # "Bookmark"
    "endorsers",  # "Which authors of this paper ...""
]
HUGGINGFACE_REMOVE_CLASSES = [
    "SVELTE_HYDRATER",  # left sidebar
    "max-w-4xl mx-auto",  # "Join the Hugging Face ..."
]

# ===================================== #

REMOVE_TAGS = [
    *COMMON_REMOVE_TAGS,
    *WIKIPEDIA_REMOVE_TAGS,
    *ARXIV_ORG_REMOVE_TAGS,
]
REMOVE_CLASSES = [
    *COMMON_REMOVE_CLASSES,
    *GOOGLE_REMOVE_CLASSES,
    *COM_163_REMOVE_CLASSES,
    *WIKIPEDIA_REMOVE_CLASSES,
    *DOC_PYTHON_REMOVE_CLASSES,
    *AZURE_REMOVE_CLASSES,
    *WEIBO_REMOVE_CLASSES,
    *WEIXIN_REMOVE_CLASSES,
    *ARXIV_ORG_REMOVE_CLASSES,
    *HUGGINGFACE_REMOVE_CLASSES,
]
