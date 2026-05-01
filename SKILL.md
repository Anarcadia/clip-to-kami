---
name: clip-to-kami
description: |
  Convert WeChat articles, web pages, EPUB e-books, and local Markdown/txt files into
  beautifully typeset Kami-styled PDFs with automatic page numbers. Use whenever the user
  wants to turn a link, article, blog post, WeChat public account post, EPUB e-book, or
  markdown file into a printable PDF.
  Trigger on phrases like "转成 PDF", "生成 PDF", "打印", "保存为 PDF", "排版",
  "make PDF", "convert to PDF", "print this article", "save as PDF",
  "把这个链接转成 PDF", "微信文章转 PDF", "网页转 PDF", "Markdown 转 PDF",
  "epub 转 PDF", "电子书转 PDF", "epub 排版".
  Also trigger when the user mentions Kami, WeasyPrint, or document typesetting.
  The skill handles four input types automatically: WeChat URLs (mp.weixin.qq.com),
  regular web pages, EPUB files (.epub), and local files (.md, .txt).
triggers:
  - "转成PDF"
  - "生成PDF"
  - "打印"
  - "保存为PDF"
  - "排版"
  - "make PDF"
  - "convert to PDF"
  - "print this article"
  - "微信文章转PDF"
  - "网页转PDF"
  - "Markdown转PDF"
  - "md转PDF"
  - "epub转PDF"
  - "电子书转PDF"
  - "epub排版"
  - "Kami"
  - "WeasyPrint"
platforms:
  - openclaw
  - claude-code
  - cursor
  - codex
  - gemini-cli
  - windsurf
  - kilo
  - opencode
  - goose
  - roo
metadata:
  openclaw:
    emoji: "📄"
    requires:
      anyBins: ["python3"]
---

# clip-to-kami · 链接/文章/笔记/EPUB 转 Kami PDF

将微信文章、网页链接、EPUB 电子书或本地 Markdown/txt 文件一键转换为 Kami 排版风格的可打印 PDF。羊皮纸底色、衬线字体、自动页码。

## 支持四种输入

| 输入类型 | 自动检测 | 抓取/解析方式 | 示例 |
|---------|---------|---------|------|
| **微信文章** | URL 包含 `mp.weixin.qq.com` | Playwright（带 stealth）→ `#js_content` 选择器 | `https://mp.weixin.qq.com/s/xxxxx` |
| **普通网页** | `http://` 或 `https://` | Playwright（带 stealth）→ readability-lxml 正文提取 → 选择器级联兜底 | `https://example.com/blog/post` |
| **EPUB 电子书** | 路径以 `.epub` 结尾 | 解析 zip → OPF/NCX → 按 spine 顺序合并章节 → 提取图片到本地 | `~/Books/三体.epub` |
| **本地文件** | 无 scheme，文件存在，非 .epub | 直接读取 | `./notes.md`, `article.txt` |

## 通用网页支持等级

| 等级 | 站点类型 | 说明 |
|---|---|---|
| **A** | 微信公众号 | 专属通道，图片本地化，发布时间多通道 |
| **B** | SSR 博客 / 新闻站 / Substack / 知乎专栏 / 个人独立博客 | readability 自动提取，零参数可用 |
| **C** | SPA / 懒加载 / 需登录前页面 | 需要传 `--wait-selector`、`--scroll`、`--timeout` |
| **D** | Cloudflare 高级挑战 / 付费墙 / Medium shadow DOM | 不支持，脚本会识别并提示 |

## 快速使用

### 命令行

```bash
# 微信文章（自动保存到 ~/Downloads/clip-to-kami/20260425-1745_文章标题/）
python3 scripts/convert.py "https://mp.weixin.qq.com/s/xxxxx"

# 指定自定义输出路径
python3 scripts/convert.py "https://example.com/blog/post" -o ~/Desktop/my.pdf

# 本地 Markdown
python3 scripts/convert.py "./my-article.md" -t "自定义标题" -a "作者名"

# 同时生成黑白打印友好版本（纯白底色）
python3 scripts/convert.py "./notes.md" --bw

# 不保存 HTML 源文件
python3 scripts/convert.py "./notes.md" --no-html

# SPA / 懒加载网页：等特定选择器 + 滚动触发懒加载
python3 scripts/convert.py "https://spa.example.com/post/123" --wait-selector "article.post" --scroll --timeout 45

# 手动指定正文容器（readability 抽错了的场合）
python3 scripts/convert.py "https://weird-blog.example.com/x" --raw-selector ".entry-content"

# 调试：关闭 stealth 观察反爬情况
python3 scripts/convert.py "https://xxx" --no-stealth

# EPUB 电子书转 Kami PDF（自动按 spine 顺序合并章节、提取图片）
python3 scripts/convert.py ~/Books/三体.epub
python3 scripts/convert.py ~/Books/novel.epub --bw          # 同时输出黑白版
python3 scripts/convert.py ~/Books/book.epub -t "自定义标题" -a "作者名"
```

### 新增的 CLI 参数（Phase 1）

| 参数 | 说明 |
|---|---|
| `--extractor {auto,readability,selector,raw}` | 正文提取策略，默认 `auto`（readability → selector 级联兜底）|
| `--raw-selector <css>` | 手动指定正文容器，隐式设 `--extractor=raw` |
| `--wait-selector <css>` | SPA 场景：等指定元素出现再抓 |
| `--scroll` | 滚动到底部触发懒加载图片/内容 |
| `--timeout <秒>` | 导航/等待超时，默认 30 |
| `--no-stealth` | 关闭 playwright-stealth（调试用）|
| `--no-image-download` | 跳过图片本地化，保留远程 URL |
| `--use-xcrawl` | 启用 XCrawl API 作为首选（需要 `~/.xcrawl/config.json`）|

### 在 Agent 对话中使用

用户只需提供一个 URL 或文件路径即可。

**Agent 初始化时，应主动询问用户：**

> "是否需要同时生成纯白底色版本（适合黑白打印）？
> 选择'是'会输出两份：`{标题}-kami.pdf`（羊皮纸）和 `{标题}-bw.pdf`（纯白）"

如果用户未明确回答，默认只生成一份（羊皮纸版本）。

示例对话：

> "把这个微信文章转成 PDF：`https://mp.weixin.qq.com/s/xxxxx`"

> "把 `~/notes/ideas.md` 排版成 Kami PDF"

> "帮我打印这个网页：`https://example.com/article`"

## 安装依赖

```bash
# 核心依赖
pip install weasyprint beautifulsoup4 markdown playwright readability-lxml playwright-stealth

# Playwright 浏览器
playwright install chromium

# macOS 系统库（WeasyPrint 需要）
brew install pango gdk-pixbuf cairo

# XCrawl 可选（强 JS 站点加速，需 API key）
# 配置 ~/.xcrawl/config.json: {"XCRAWL_API_KEY": "your-key"}
```

**macOS 特别注意**：WeasyPrint 需要设置库路径：

```bash
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH
```

## 工作流程

### Step 1 · 检测输入类型

```python
from urllib.parse import urlparse

def detect_input_type(input_str):
    parsed = urlparse(input_str)
    if parsed.scheme in ("http", "https"):
        if "mp.weixin.qq.com" in parsed.netloc:
            return "wechat"      # 微信文章
        return "webpage"         # 普通网页
    return "local"               # 本地文件
```

### Step 2 · 获取内容

| 类型 | 方法 | 说明 |
|------|------|------|
| 微信 | Playwright + stealth | 真实 UA + viewport + 反检测，提取 `#js_content`，带重试 |
| 网页 | Playwright + stealth → readability → selector 级联 | 默认零参数，对 SSR 博客效果好；`--use-xcrawl` 切 API 模式 |
| EPUB | zipfile + ElementTree | 解析 `META-INF/container.xml` → OPF（metadata + manifest + spine）→ NCX 取章节标题 → 按 spine 顺序拼接章节，重写跨章节锚点；图片解压到 `output_dir/images/` |
| 本地 | 直接读取 | 自动解析 YAML frontmatter（提取 title/author/url），Markdown 转 HTML |

**图片本地化**：抓取后脚本自动下载所有图片到 `output_dir/images/`（微信域自动带 `Referer: mp.weixin.qq.com/`，其他网页从 source URL 派生 Referer），HTML 中远程 URL 替换为本地路径。按 URL 去重，确保 PDF 中图片不会因 CDN 过期而丢失。

**Cloudflare 检测**：抓到的页面标题/首段匹配"Just a moment"、"cf-browser-verification"等关键词时，脚本会打印明确警告。

### Step 3 · 清洗 HTML

清洗函数的核心原则：**保留所有内容元素，只移除无用样式。**

关键规则（详见 `references/pitfalls.md`）：

1. **不要跳过 `section` 元素** — 微信图片包裹在 `section` 中
2. **优先 `data-src` 而非 `src`** — 微信懒加载机制
3. **过滤 SVG 占位符** — `src="data:image/svg+xml..."`
4. **保留 `table`、`pre`、`blockquote` 等结构元素**

### Step 4 · 填入 Kami 模板

使用 `assets/templates/long-doc.html`（或系统 Kami skill 中的模板）：

- 替换占位符：`{{文档标题}}`、`{{作者}}`、`{{摘要}}` 等
- 替换目录和正文区域为实际内容
- 页码已由模板 CSS 的 `@page` 规则自动生成，无需额外处理

### Step 5 · 生成 PDF

```python
from weasyprint import HTML
HTML('document.html').write_pdf('output.pdf')
```

## 输出目录

**默认行为**（不指定 `-o`）：

```
~/Downloads/
└── clip-to-kami/
    └── 20260425-1745_不和AI正面竞争/
        ├── 不和AI正面竞争.pdf
        └── 不和AI正面竞争.html   # 中间 HTML 源文件
```

- 每次导出自动创建以 **时间戳 + 标题** 命名的子文件夹
- 子文件夹确保同一篇文章多次导出不会互相覆盖
- 同时输出 PDF 和 HTML 源文件（可用 `--no-html` 跳过 HTML）

**自定义路径**（指定 `-o`）：

```bash
python3 scripts/convert.py "..." -o ~/Desktop/我的文档.pdf
```

**黑白双版本**（使用 `--bw`）：

```
~/Downloads/clip-to-kami/
└── 20260425-1745_文章标题/
    ├── 文章标题-kami.pdf      ← 羊皮纸（原版）
    ├── 文章标题-bw.pdf        ← 纯白（黑白打印友好）
    ├── 文章标题-kami.html     ← 原版 HTML 源文件
    └── 文章标题-bw.html       ← 纯白 HTML 源文件
```

## 输出特性

| 特性 | 状态 | 说明 |
|------|------|------|
| 羊皮纸底色 | ✅ | Kami 默认 `#f5f4ed` |
| 衬线中文字体 | ✅ | TsangerJinKai02（如可用） |
| 自动页码 | ✅ | 每页底部显示页码 + 标题 |
| 封面无页码 | ✅ | `@page:first` 自动隐藏 |
| 代码块 | ✅ | `pre > code` 样式 |
| 表格 | ✅ | `.kami-table` 样式 |
| 图片 | ✅ | 远程图片嵌入（注意微信图片可能有防盗链） |
| 引用块 | ✅ | `blockquote` 左侧边框 |
| 黑白打印版本 | ✅ | `--bw` 生成纯白底色 `-bw.pdf` |

## 文件结构

```
clip-to-kami/
├── SKILL.md                    # 本文件
├── scripts/
│   └── convert.py              # 核心转换脚本
├── references/
│   └── pitfalls.md             # 踩坑点与注意事项
├── assets/
│   └── templates/
│       └── long-doc.html       # Kami 长文档模板（如系统 Kami 不可用）
└── evals/
    └── evals.json              # 测试用例
```

## 常见问题

**Q: 为什么 PDF 里图片显示不出来？**
A: 微信文章的图片已自动下载到本地（`output_dir/images/`），通常不会有问题。如果仍然缺失：
- 检查终端输出中是否有 `WARNING: Failed to download image` 提示
- 微信 CDN 可能临时不可用，稍后重试
- 如果触发了微信验证页（"环境异常"），抓取到的 HTML 不包含正文内容，需手动保存网页 HTML 后用本地文件模式转换

**Q: 文件输出到哪里了？**
A: 默认输出到 `~/Downloads/clip-to-kami/<时间戳>_<标题>/` 子文件夹中，包含 PDF 和 HTML 源文件。如需指定路径，使用 `-o` 参数。

**Q: WeasyPrint 报错 "cannot load library"？**
A: 脚本已自动在 macOS 上设置 `DYLD_LIBRARY_PATH=/opt/homebrew/lib`。如仍报错，确保已安装 Homebrew 依赖：`brew install pango gdk-pixbuf cairo`

**Q: 字体不是 Kami 的衬线字体？**
A: 确保 TsangerJinKai02 字体文件在 `~/.claude/skills/kami/assets/fonts/` 或脚本能找到的位置。

**Q: 页码没显示？**
A: Kami 模板已内置页码。如果缺失，检查模板是否完整加载。

## 微信文章降级方案

当 Playwright 无法正常抓取微信文章时（如触发验证页、网络问题），可用以下降级流程：

1. **浏览器手动保存**：在浏览器中打开微信文章 → 右键"另存为网页（仅 HTML）"→ 保存到本地
2. **本地文件转换**：`python3 convert.py ./saved-article.html -t "文章标题" -s "https://mp.weixin.qq.com/s/xxx"`
3. **注意**：手动保存的 HTML 中图片仍为远程 URL，可能受防盗链影响。建议在保存 HTML 的同时手动下载图片

如有专业微信抓取工具（如 `wechat-article-to-markdown`），推荐先用其抓取 Markdown + 图片，再用 clip-to-kami 排版输出。

## 参考文献

- 踩坑点详解：`references/pitfalls.md`
- Kami 设计系统：`~/.claude/skills/kami/references/design.md`
- Kami 生产指南（含 WeasyPrint 渲染 bug 手册）：`~/.claude/skills/kami/references/production.md`
- Kami 写作指南：`~/.claude/skills/kami/references/writing.md`
- Kami 反面教材：`~/.claude/skills/kami/references/anti-patterns.md`
- Kami Brand Profile 模板：`~/.claude/skills/kami/references/brand-profile.md`
