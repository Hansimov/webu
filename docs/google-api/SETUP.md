# ggsc (GooGle-SearCh) — 环境搭建指南

> 从零开始搭建 ggsc Google 搜索服务所需的全部依赖和环境配置。

---

## 1. 前置依赖

### 1.1 Python 环境

```bash
# 推荐使用 conda
conda activate ai
python --version  # 需要 Python 3.11+
```

### 1.2 安装 webu 包

```bash
cd /home/asimov/repos/webu
pip install -e .
```

### 1.3 Chrome 浏览器

undetected-chromedriver 需要 Chrome/Chromium：

```bash
# Ubuntu/Debian
sudo apt install google-chrome-stable
# 或
sudo apt install chromium-browser

# 验证
google-chrome --version
```

### 1.4 Playwright 浏览器

```bash
playwright install chromium
```

---

## 2. 代理配置

### 2.1 本地 HTTP 代理

ggsc 使用两个本地 HTTP 代理，需要确保它们已运行：

| 代理 | 端口 | 用途 |
|------|------|------|
| proxy-11111 | 11111 | HTTP 代理（轮换 #1）|
| proxy-11119 | 11119 | HTTP 代理（轮换 #2）|

验证代理可用：

```bash
# 测试代理连通性
curl -x http://127.0.0.1:11111 https://httpbin.org/ip
curl -x http://127.0.0.1:11119 https://httpbin.org/ip
```

### 2.2 自定义代理

如需使用其他代理，可通过环境变量或 CLI 参数指定：

```bash
ggsc start --proxies "http://1.2.3.4:8080,http://5.6.7.8:8080"
```

---

## 3. VLM 配置（CAPTCHA 处理）

CAPTCHA 自动处理需要 VLM API 配置：

```bash
# 配置文件路径
configs/captcha.json
```

---

## 4. 文件结构

```
src/webu/google_api/
├── __init__.py          # 模块导出
├── __main__.py          # python -m webu.google_api 入口
├── cli.py               # ggsc CLI 工具
├── constants.py         # 配置常量（端口、日志路径等）
├── parser.py            # Google 搜索结果解析器
├── proxy_manager.py     # 代理管理器
├── scraper.py           # 浏览器搜索引擎
└── server.py            # FastAPI 服务
```

---

## 5. 快速验证

```bash
# 1. 验证安装
ggsc --help

# 2. 检查代理状态
ggsc proxy-status

# 3. 执行代理健康检查
ggsc proxy-check

# 4. 手动搜索测试
ggsc search "Python programming"

# 5. 启动服务
ggsc start

# 6. 验证服务
curl http://127.0.0.1:7800/health
curl "http://127.0.0.1:7800/search?q=hello+world"

# 7. 查看代理状态
curl http://127.0.0.1:7800/proxy/status
```

---

## 6. 常见问题

### Chrome 启动失败

```bash
# 确保已安装 Chrome
which google-chrome || which chromium-browser

# 如果是 headless 服务器，安装 xvfb
sudo apt install xvfb
```

### 代理不可用

```bash
# 检查代理端口是否在监听
ss -tlnp | grep -E "11111|11119"

# 手动测试代理
curl -x http://127.0.0.1:11111 https://www.google.com -o /dev/null -w "%{http_code}" 2>/dev/null
```
