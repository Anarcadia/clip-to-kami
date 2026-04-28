# clip-to-kami

把**微信文章、网页链接、EPUB 电子书、本地 Markdown/txt**一键转成 **Kami 排版风格**的可打印 PDF。羊皮纸底色、衬线中文字体、自动页码、封面页。

> 一条命令从 URL 到印刷品质 PDF。

<!-- ══════════════════════════════════════════════════════════════════════════
     ⚠️ USER-PROTECTED CONTENT — DO NOT MODIFY ⚠️
     本节由仓库作者亲手撰写。任何 AI / Agent 在自动更新此 README 时，
     **不得改写、删除、重排或"优化"** 本 USER-PROTECTED 区块内的任何文字。
     仅仓库作者本人可编辑此区块。
     ══════════════════════════════════════════════════════════════════════════ -->

## 致敬

本 Skill 是在 [**Kami**](https://github.com/tw93/kami) 原作者 [@Tw93](https://github.com/tw93) 的基础上做的流程优化，**设计灵感全归于原作者**。

> Kami（紙・かみ）是 Tw93 为 AI 时代打造的文档设计系统——**"Good content deserves good paper."** 用一套统一的约束语言，让 Agent 输出的文档稳定、克制、可交付。clip-to-kami 在 Kami 的排版基底之上扩展了输入端（微信 / 网页 / EPUB / 本地文件），定位是 Kami 的**内容剪藏前置流水线**。

<!-- ══════════════ END USER-PROTECTED CONTENT ══════════════ -->

---

## 功能速览

- **四种输入一个入口**：微信公众号文章、普通网页、EPUB 电子书、本地 `.md`/`.txt`/`.html` 都走同一个命令
- **EPUB 自动合并**：解析 EPUB → 按 spine 顺序拼接章节 → 提取图片 → 一次产出整本 Kami PDF
- **自动抓取 + 正文提取**：Playwright（带 stealth 反爬）抓页面，readability-lxml 提取正文，CSS 选择器级联兜底
- **图片本地化**：所有图片下载到输出目录，PDF 不会因为远程 CDN 过期而变成破图
- **微信专属优化**：`#js_content` 选择器、`create_time` 发布时间解析、图片防盗链 `Referer` 自动带上
- **Kami 排版模板**：羊皮纸底色、TsangerJinKai02 衬线中文字体、自动目录与页码、封面页
- **黑白打印支持**：`--bw` 一并生成纯白底色版本，更适合激光打印机
- **SPA/反爬友好参数**：`--wait-selector`、`--scroll`、`--timeout` 处理懒加载与慢站点

---

## 支持等级

| 等级 | 站点类型 | 是否开箱即用 |
|---|---|---|
| **A** | 微信公众号文章 | ✅ 专属通道，图片本地化，多通道解析发布时间 |
| **B** | SSR 博客 / 新闻站 / Substack / 知乎专栏 / 个人独立博客 | ✅ readability 自动提取，零参数 |
| **C** | SPA / 懒加载 / 动态渲染 | ⚠️ 需传 `--wait-selector`、`--scroll`、`--timeout` |
| **D** | Cloudflare 高级挑战 / 付费墙 / Medium shadow DOM | ❌ 不支持，脚本会识别并提示手动保存 HTML |
| **E** | EPUB 电子书（`.epub`）| ✅ 离线解析，按 spine 顺序合并章节，提取图片 |

---

## 3 步安装

### 1. 克隆仓库

```bash
git clone https://github.com/Anarcadia/clip-to-kami.git
cd clip-to-kami
```

### 2. 一键安装

```bash
bash install.sh
```

脚本会自动：
- 检查 Python ≥ 3.9
- 安装 Homebrew 系统库（macOS：pango、gdk-pixbuf、cairo）
- 安装 pip 依赖（requirements.txt）
- 下载 Playwright Chromium
- 跑一遍 `doctor.py` 验证环境

**系统支持**：macOS（Intel/Apple Silicon）与 Linux（Debian/Ubuntu 需手动 apt 装对应库）。Windows 用户请在 WSL2 内运行。

### 3. 跑一个示例

```bash
# 微信文章（输出到 ~/Downloads/clip-to-kami/时间戳_标题/）
python3 scripts/convert.py "https://mp.weixin.qq.com/s/xxxxxx"

# 普通网页
python3 scripts/convert.py "https://www.ruanyifeng.com/blog/xxx.html"

# 本地 Markdown
python3 scripts/convert.py ./my-notes.md

# EPUB 电子书（按 spine 顺序合并所有章节，提取图片）
python3 scripts/convert.py ~/Books/三体.epub
```

---

<!-- ══════════════════════════════════════════════════════════════════════════
     ⚠️ USER-PROTECTED CONTENT — DO NOT MODIFY ⚠️
     本节由仓库作者亲手撰写。任何 AI / Agent 在自动更新此 README 时，
     **不得改写、删除、重排或"优化"** 本 USER-PROTECTED 区块内的任何文字。
     仅仓库作者本人可编辑此区块。
     ══════════════════════════════════════════════════════════════════════════ -->

## 自然语言调用 Skill（给非编程用户）

如果你用的是支持 **Skill 系统** 的 AI Agent —— 比如 **Claude Code** 终端、**OpenClaw**、或类似 **Hermes Agent** 的工具 —— 你**不需要**敲 `python3 scripts/convert.py ...` 这种命令行。直接用一句话告诉 AI 你想做什么，它会自己识别意图、调用本 Skill 完成排版。

### 怎么说（对话示例）

| 你想做什么 | 直接对你的 AI 助手说 |
|---|---|
| 微信文章转 PDF | "把这个微信文章转成 PDF：`https://mp.weixin.qq.com/s/xxxxxx`" |
| 网页文章转 PDF | "帮我把 https://www.ruanyifeng.com/blog/xxx.html 排版打印" |
| EPUB 电子书转 PDF | "把 `~/Books/三体.epub` 转成 Kami PDF" |
| 本地 Markdown 排版 | "把 `~/notes/想法.md` 转成可打印的 PDF" |
| 同时要黑白版 | 在请求结尾加一句"顺便给我生成黑白打印友好版" |
| 自定义标题作者 | "标题改成《XXX》，作者写 XXX" |

不需要记参数、不需要查 `--help`。AI 看到你提到的关键词（**PDF、转换、排版、打印、Kami、转电子书** 之类），就知道该用本 Skill。

### "黑底白字的路由提示"是什么

当 AI 听完你的请求、决定调用某个 Skill 时，终端会闪过一行**反白（黑底白字）的提示**，类似：

```
🔧 Using skill: clip-to-kami
```

或者图形界面里会出现一个 **clip-to-kami** 的徽章。这就是 **Skill 路由（Routing）**——你可以理解成：

> AI 像一个有很多工具的助手。你给它一个任务，它会先在脑子里**挑出最合适的那个工具**，然后才动手。"路由"就是这个**挑选 + 跳转**的过程。
> 
> 黑底白字的提示，就是 AI 告诉你：**"我决定用这把工具"**。

#### 路由对了 vs 路由错了

- ✅ **看到 `clip-to-kami`** → AI 找对了路，正在用本 Skill 给你转 PDF
- ⚠️ **跳出别的 Skill 名字**（比如 `kami`、`baoyu-translate`、`web-browser`）→ AI 走错了路。这时只要更明确地说一句：
  > "**用 clip-to-kami 这个 Skill** 把 `xxx` 转成 PDF"
  
  把 Skill 名字直接念出来，等于强行指定路由
- ❓ **完全没出现 Skill 提示** → AI 没有识别到 Skill 触发词，可能它身上根本没装这个 Skill。检查 `~/.claude/skills/clip-to-kami/` 或对应工具的 Skill 目录是否安装了本仓库

### 进阶：触发词清单

下面这些词出现在你的话里，多数 Skill-aware Agent 都会自动路由到本 Skill：

`转成 PDF` / `生成 PDF` / `保存为 PDF` / `打印这篇` / `排版` / `Kami` / `WeasyPrint` / `epub 转 PDF` / `电子书转 PDF` / `epub 排版` / `网页转 PDF` / `Markdown 转 PDF` / `微信文章转 PDF`

记不住也没关系，**说人话就行**——这些只是兜底关键词。

<!-- ══════════════ END USER-PROTECTED CONTENT ══════════════ -->

---

## 常用命令

```bash
# 指定输出路径
python3 scripts/convert.py "https://..." -o ~/Desktop/my.pdf

# 同时生成黑白打印版
python3 scripts/convert.py "https://..." --bw

# SPA 站点：等正文元素出现 + 滚动触发懒加载
python3 scripts/convert.py "https://spa.example.com/post" \
  --wait-selector "article" --scroll --timeout 45

# 手动指定正文容器（readability 抽错时）
python3 scripts/convert.py "https://..." --raw-selector ".post-content"

# 跳过图片下载（保留远程 URL）
python3 scripts/convert.py "https://..." --no-image-download

# 本地文件指定标题/作者（覆盖 frontmatter）
python3 scripts/convert.py ./notes.md -t "我的笔记" -a "张三"
```

完整 CLI 参数见 `python3 scripts/convert.py --help`。

---

## 输出示例

默认行为：每次导出创建独立子文件夹，避免互相覆盖。

```
~/Downloads/clip-to-kami/
└── 20260426-1428_文章标题/
    ├── 文章标题.pdf          ← Kami 羊皮纸版
    ├── 文章标题.html         ← 中间 HTML 源文件（可 --no-html 关闭）
    └── images/               ← 本地化后的图片
        ├── img_001_ab12...jpg
        └── ...
```

开启 `--bw` 额外输出 `-bw.pdf` 与 `-bw.html`。

---

## 常见问题

### Q: WeasyPrint 报错 `cannot load library 'libgobject-2.0-0'`？
A: macOS 上需要 Homebrew 的 Pango/Cairo 库。脚本已自动设 `DYLD_LIBRARY_PATH=/opt/homebrew/lib`，若仍报错：
```bash
brew install pango gdk-pixbuf cairo
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH
```

### Q: PDF 里图片全没了？
A: 脚本会打印 `Images: N downloaded, M failed`。常见原因：
- 微信触发验证页（标题含"环境异常"）→ 改用"浏览器另存为 HTML"+ 本地文件模式
- 普通站点的签名 URL 过期 → 稍后重试
- CDN 防盗链 → 脚本已从 source URL 派生 Referer，覆盖多数场景

### Q: 微信文章标题是 "Just a moment..."？
A: 触发了 Cloudflare 挑战（非微信本站），脚本会打印警告。解决：浏览器手动保存 HTML 后用本地文件模式：
```bash
python3 scripts/convert.py ./saved.html -t "标题" -s "原始URL"
```

### Q: 字体不是 Kami 的衬线字体？
A: TsangerJinKai02 是商业字体，本仓库默认带一份，位于 `assets/fonts/`。如缺失会回退到系统字体（Songti/STSong 等）。

### Q: 页码没显示？
A: Kami 模板通过 `@page` CSS 自动添加页码。若 PDF 没有页码，检查 `assets/templates/long-doc.html` 是否完整。

### Q: 如何自诊环境？
A: 随时运行 `python3 scripts/doctor.py`，会给出每一项的 ✅/❌ 和修复命令。

---

## 文件结构

```
clip-to-kami/
├── README.md                   # 本文件
├── SKILL.md                    # Skill 规范（AI agent 可加载）
├── install.sh                  # 一键安装脚本
├── requirements.txt            # Python 依赖
├── scripts/
│   ├── convert.py              # 核心转换入口
│   └── doctor.py               # 环境自检
├── assets/
│   ├── fonts/                  # 字体文件
│   └── templates/
│       └── long-doc.html       # Kami 长文模板
├── references/
│   └── pitfalls.md             # 踩坑点详解
└── evals/
    └── evals.json              # 测试用例
```

---

## 踩坑与限制

- 微信文章图片 CDN 会过期 → 脚本自动下载到本地规避
- SPA 站点默认抓不到正文 → 用 `--wait-selector` + `--scroll`
- Cloudflare Turnstile、Medium shadow DOM、付费墙 → 不支持
- readability-lxml 对极少数非常规布局的页面会抽错 → `--raw-selector` 手动指定

更多详见 [`references/pitfalls.md`](references/pitfalls.md)。

---

## 许可证

MIT License. 详见 [`LICENSE`](LICENSE)。

字体 **TsangerJinKai02** 属于仓颉字库商业授权，仅供个人学习使用；商用请自行获取授权或替换为开源字体。
