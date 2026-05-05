# Changelog

记录 clip-to-kami 的关键修改、原因、验证方式与遗留风险。后续若有变更，按时间倒序在顶部追加新条目。

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
