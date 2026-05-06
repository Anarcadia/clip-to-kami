# Changelog

记录 clip-to-kami 的关键修改、原因、验证方式与遗留风险。后续若有变更，按时间倒序在顶部追加新条目。

---

## 2026-05-07｜本地 Markdown 相对路径图片修复 + 封面"来源"不再回落本地路径

**触发原因**：proma 工作区分支测试中发现两个隐患，回流到 root 主线一次性修复。

### Bug 1：本地 Markdown 相对路径图片在 PDF 中全部丢失

- **场景**：本地 `.md` 文件含 `![img](images/foo.png)` 相对路径引用，转 PDF 后图片缺失。
- **根因**：`markdown.markdown()` 生成 `<img src="images/foo.png">` 后 HTML 写入 `~/Downloads/clip-to-kami/.../output.html`，WeasyPrint 从 output.html 所在目录解析 src，找不到图。
- **修复**：`read_local_file()`（`scripts/convert.py:425`）在 markdown→html 之后用 BeautifulSoup 遍历 `<img>`，将相对路径 src 解析为基于 md 文件所在目录的绝对路径；http/https/data:/file:// 协议头与绝对路径跳过不动；解析后的绝对路径必须 `.exists()` 才会写回，避免误改。
- **验证**：诺兰文章复测，PDF 从 ~50 KB（无图）恢复到 ~5.8 MB（21 张图嵌入）。

### Bug 2：PDF 封面"来源"会打印本地文件路径

- **场景**：处理无 frontmatter 的本地 md 时，封面"来源"字段会显示完整本地绝对路径（形如 `/Users/<user>/.../foo.md`），违反"封面禁止暴露本地路径，必须回溯原文 URL 或作者"的产品约束。
- **根因**：
  1. `read_local_file()` 的 source_url 兜底链最末端是 `str(path)`（本地绝对路径）。
  2. `fill_kami_template()` 直接 `subtitle = f"来源: {source}"`，无任何 sanitization。
- **修复**：
  1. `read_local_file()` 兜底链改为 `... or author or title`，删除 `str(path)` 兜底——宁可用作者名/文件名（来自 frontmatter title 或 path.stem），也不暴露本地路径。
  2. `fill_kami_template()` 增加 `_looks_local()` 守卫：source 以 `/`、`file://`、`~` 开头，或匹配 Windows 盘符，或包含 `/Users/`、`/home/` 时，降级为 `author or title or "本地文档"`。这一层守卫覆盖了 `--source` CLI 参数误传本地路径、EPUB 兜底路径泄漏等所有场景。
- **副作用**：source 被降级后，eyebrow 文案会从"网页归档"自动切到"文档归档"（line 1076 已有 `source.startswith("http")` 判断，自洽）。

### 修改范围

只动了 `scripts/convert.py`：
- `read_local_file()`（line 425-496）：兜底链调整 + 相对路径重写
- `fill_kami_template()`（line 1019+）：增加 `_looks_local` 守卫

### 已知遗留

- 若 md 文件**完全无 frontmatter** 且文件名又是无意义的 `untitled.md` / `xxx.md`，封面"来源"会显示文件名 stem，仍不算理想——但比本地绝对路径好。后续可考虑加 CLI 参数 `--source-fallback` 让用户显式指定。
- 相对路径重写只处理 `<img>`，未处理 `<a href>`、`<link href>`、CSS `background-image`，目前无场景需求。

---

## 2026-05-05｜微信图片 URL 协议补全更鲁棒 + 收集阶段过滤无效 URL

**触发原因**：抓取部分微信文章时，零星图片下载失败，控制台日志出现 `unknown url type` 之类的协议错误，且本地 images 文件编号断档（如 img_002~005 缺 img_001）。

### 背景

`localize_images()`（旧名 `download_wechat_images`）从 HTML 收集 `<img>` 的 `data-src`/`src` 当作下载列表。微信文章里的 `src` 实际可能出现这些"非常规 URL"：

| 形态 | 示例 | 旧逻辑 | 新逻辑 |
|------|------|--------|--------|
| 完整 URL | `https://mmbiz.qpic.cn/x.png` | ✅ 正常 | ✅ 正常 |
| 协议相对 | `//mmbiz.qpic.cn/x.png` | ✅ 补 `https:` | ✅ 同 |
| 站内绝对（带 source_url） | `/path/x.png` | ✅ urljoin 解析 | ✅ 同 |
| **空白 src** | `"   "` | ❌ urllib 报错 | ✅ strip 后跳过 |
| **`javascript:`** | `javascript:void(0)` | ❌ 进入下载报错 | ✅ 收集阶段就跳过 |
| **裸主机（无 source_url）** | `mmbiz.qpic.cn/x.png` | ❌ 静默 skip 丢图 | ✅ 兜底补 `https://` 试下载 |
| `data:` 内联 | `data:image/...` | ✅ 跳过 | ✅ 跳过（保留） |

### 修改文件

只动了 `scripts/convert.py` 的 `localize_images()` 函数（line 94~106）。

```diff
-        src = img.get("data-src") or img.get("src", "")
-        if not src or src.startswith("data:"):
+        src = (img.get("data-src") or img.get("src", "") or "").strip()
+        if not src or src.startswith(("data:", "javascript:")):
             skipped += 1
             continue
         if src.startswith("//"):
             src = "https:" + src
         # Resolve relative URLs against source
         if source_url and not src.startswith(("http://", "https://")):
             src = urljoin(source_url, src)
         if not src.startswith(("http://", "https://")):
-            skipped += 1
-            continue
+            # Fallback: bare host or relative path with no source_url base.
+            # Force https:// so we at least try the download instead of dropping silently.
+            src = "https://" + src.lstrip("/")
```

### 验证

`scripts/convert.py` 的协议补全分支单测，9 个边界用例全部通过：

| 输入 | source_url | 预期 |
|------|-----------|------|
| `https://mmbiz.qpic.cn/x.png` | 微信文章 URL | 不变 ✅ |
| `http://mmbiz.qpic.cn/x.png` | 微信文章 URL | 不变 ✅ |
| `//mmbiz.qpic.cn/x.png` | 微信文章 URL | `https:` 前缀 ✅ |
| `/path/x.png` | 微信文章 URL | urljoin 拼成 `https://mp.weixin.qq.com/path/x.png` ✅ |
| `mmbiz.qpic.cn/x.png` | 空 | 兜底补 `https://` ✅ |
| 空字符串 / 纯空白 | — | skip ✅ |
| `data:image/...` | — | skip ✅ |
| `javascript:void(0)` | — | skip ✅ |

### 风险与遗留

1. **裸主机 + 有 source_url 的 case**：`urljoin("https://mp.weixin.qq.com/s/xxx", "mmbiz.qpic.cn/x.png")` 会拼成 `https://mp.weixin.qq.com/s/mmbiz.qpic.cn/x.png`（错的），下载会失败但不会再报"协议错"。这是 `urljoin` 的固有行为，本次未额外处理——微信文章里这种形态极少见。
2. **裸主机补 `https://` 的假设**：如果资源本来是 `http://`（极小概率），强补 `https://` 可能导致下载失败。可接受 —— 主流图床（mmbiz.qpic.cn 等）支持 https。
3. **空 src 的图片在正文里仍以 `![]()` 出现**：未改写 markdownify，对阅读基本无害。

### 上游同步信息

本次修改与 `Factory/wechat-article-to-markdown/main.py` 的同期修复属同源问题。后者是 Root 内部工具，clip-to-kami 是对外发布工具包，两者保持代码独立但修复精神一致。详见 [Factory/wechat-article-to-markdown/HANDOFF.md](../../Factory/wechat-article-to-markdown/HANDOFF.md)（仅 Root 内可见）。

### 相关文件

- 工具入口：`scripts/convert.py`（函数 `localize_images()`，line 70~138）
- 同步副本：`~/.claude/skills/clip-to-kami/scripts/convert.py`（user 版，函数名为 `download_wechat_images`，结构稍简但同样修复）
