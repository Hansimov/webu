"""向后兼容层 — 已弃用，请使用 server.py。

此文件保留用于旧代码的兼容性。
新代码请直接使用:
    from webu.gemini.server import create_gemini_server, run_gemini_server
"""

from .server import create_gemini_server, run_gemini_server

# 保留旧名称作为别名
create_gemini_app = create_gemini_server
run_gemini_api = run_gemini_server

if __name__ == "__main__":
    run_gemini_server()
