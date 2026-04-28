# 踩坑点与注意事项

## 1. 图片丢失：section 元素被跳过

**症状**：PDF 中没有任何图片。

**原因**：清洗 HTML 时，`<section>` 元素被 `get_text()` 判定为空（只包含图片，无文本），导致整个 section 被跳过。

**修复**：不要基于文本内容跳过 `<section>`，始终递归处理子元素。

```python
# 错误 — 会丢失图片
if elem.name == 'section':
    if not elem.get_text(strip=True):
        return ''  # 图片没了！

# 正确 — 始终递归
if elem.name == 'section':
    return ''.join(process_element(c) for c in elem.children)
```

## 2. 微信图片 URL 错误

**症状**：图片显示为空白或无法加载。

**原因**：微信文章的 `<img>` 使用 `data-src` 存储原始图片 URL，`src` 只是懒加载占位符（可能是一个 1x1 SVG）。

**修复**：优先使用 `data-src`，过滤 SVG 占位符。

```python
src = elem.get('data-src', '') or elem.get('src', '')
if src and not src.startswith('data:image/svg+xml'):
    # 使用这个 src
```

## 3. macOS WeasyPrint 库加载失败

**症状**：`OSError: cannot load library 'libgobject-2.0-0'`

**原因**：macOS 上 WeasyPrint 依赖 Homebrew 安装的 Pango/GDK 库，但动态链接器找不到它们。

**修复**：设置环境变量：

```bash
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH
```

或在脚本中自动检测：

```python
import platform
if platform.system() == 'Darwin':
    os.environ['DYLD_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_LIBRARY_PATH', '')
```

## 4. 字体文件路径

**症状**：PDF 使用系统默认字体（如 Georgia），而非 Kami 的 TsangerJinKai02。

**原因**：Kami 模板中 `@font-face` 使用相对路径 `../fonts/xxx.ttf`，但如果 HTML 文件不在模板同级目录，字体加载失败。

**修复**：将字体文件复制到与 HTML 同目录，或使用绝对路径。脚本中已将字体复制到临时目录。

## 5. 页码

Kami 的 `long-doc.html` 模板已自带页码（`@bottom-center { content: counter(page) }`），封面页自动隐藏（`@page:first`）。**不需要额外添加页码。**

## 6. 微信反爬

微信域名 `mp.weixin.qq.com` 有反爬机制。使用 Playwright 模拟真实浏览器是可靠方案。curl/wget/requests 通常会被拦截。

## 7. 长文分页

WeasyPrint 会根据内容自动分页。如果文章很长，PDF 页数会很多。这是预期行为。如果需要控制单页输出，使用 `one-pager.html` 模板。

## 8. 微信图片防盗链

**症状**：图片下载返回 403 或空白图片。

**原因**：微信 CDN 检查 `Referer` 头，必须为 `https://mp.weixin.qq.com/`。

**修复**：下载时带 Referer 头：

```python
req = urllib.request.Request(url, headers={"Referer": "https://mp.weixin.qq.com/"})
```

## 9. 微信图片 CDN 过期

**症状**：PDF 生成时图片正常，过几天再打开图片消失。

**原因**：微信 CDN 图片 URL 非永久有效，过期后返回空或错误。

**修复**：抓取时立即下载图片到本地，HTML 中引用本地路径而非远程 URL。`convert.py` 已内置 `download_wechat_images()` 自动处理。

## 10. 微信代码块 CSS counter 噪声

**症状**：代码块中出现 `counter(line` 等无意义文本。

**原因**：微信代码块 `.code-snippet__fix` 使用 CSS counter 显示行号，`get_text()` 会把 counter 值当文本提取。

**修复**：过滤匹配 `^[ce]?ounter\(line` 的行。`convert.py` 的 `clean_html()` 已自动处理。

## 11. 微信发布时间在 JS 变量中

**症状**：`#publish_time` DOM 选择器返回空字符串。

**原因**：部分微信文章的发布时间不在可见 DOM 中，而是在 `<script>` 标签的 `create_time` JS 变量中。

**修复**：DOM 取不到时，用正则从 `page.content()` 中解析 `create_time: JsDecode('...')` 或 `create_time: '\d+'`。

## 12. 原生 Playwright 触发微信验证

**症状**：页面显示"环境异常，完成验证后继续"。

**原因**：微信检测到 headless Chromium 的默认 UA 和 viewport。

**缓解**：设置真实浏览器 UA 和 viewport 降低触发概率。`convert.py` 已内置。如仍触发，考虑使用 Camoufox（反检测 Firefox）或手动保存网页 HTML 后用本地文件模式转换。

---

## 通用网页抓取踩坑（Phase 1 新增）

## 13. readability 抽出空内容或过短

**症状**：`Extractor: readability output too short, falling back to selector cascade.`

**原因**：页面正文结构非常规（如 SPA 把正文放进 shadow DOM、或页面主要是视频/互动组件）。

**处理**：
1. 脚本已自动降级到 CSS 选择器级联，通常能兜回一些内容
2. 若仍不对，手动传 `--raw-selector ".some-class"` 指定正文容器
3. 可以用 `--extractor selector` 跳过 readability

## 14. SPA 页面抓到空 body

**症状**：`Content length: 0 chars` 或抓到骨架屏。

**原因**：页面是纯 JS 渲染（React/Vue SSR 失败或 SPA），`networkidle` 不等于内容已渲染。

**处理**：
- 传 `--wait-selector "article"`（或页面实际的正文容器选择器）
- 传 `--scroll` 触发懒加载
- 传 `--timeout 60` 给慢站点更多时间

## 15. Cloudflare 挑战页

**症状**：控制台打印 `WARNING: Cloudflare / bot challenge detected`，PDF 内容是"Just a moment..."。

**原因**：目标站点开启了 Cloudflare bot protection 或 Turnstile 挑战。

**处理**：
- playwright-stealth 能过一部分基础检测，但 Turnstile 这类主动挑战是过不了的
- 用浏览器手动打开页面 → 另存为 HTML → 走本地文件模式
- 或换成 Camoufox、undetected-playwright 等更激进的方案（本 skill 不内置）

## 16. 通用网页图片 CDN 防盗链

**症状**：部分图片 403，本地化后变成破图。

**原因**：许多 CDN 检查 Referer。旧版脚本的 Referer 硬编码为微信域，换了站点就失效。

**修复**：脚本自动从 source URL 派生 Referer（`https://{host}/`），覆盖大多数站点的规则。仍失败的场景：
- 需要登录态才能下载图片（如知乎付费专栏）
- 图片走签名 URL（过期或域名随机）

## 17. 相对图片 URL

**症状**：抓到的图片 src 是 `/images/foo.png` 而不是完整 URL。

**原因**：个人博客常用相对路径。

**修复**：`localize_images()` 已自动用 `urljoin(source_url, src)` 补全。如果 source_url 缺失则跳过这张图。

## 18. readability-lxml 对中文编码偶尔误判

**症状**：抽出来的正文有乱码。

**原因**：readability-lxml 默认 chardet 有时对 GBK 中文判错。

**处理**：目前没遇到严重问题（Playwright 返回的 HTML 总是 UTF-8，已从源头规避）。若出现，可切 `--extractor selector` 绕开 readability。

## 19. networkidle 在有持续连接的页面上永不到达（Phase 3 修复）

**症状**：`Page.goto: Timeout 30000ms exceeded`，即使是普通 SSR 博客（如阮一峰的博客）。

**原因**：很多站点有 analytics、WebSocket、长连接轮询，这些会让 `networkidle`（要求 500ms 无网络请求）永远不满足。

**修复**：脚本对非微信页面默认用 `domcontentloaded`，只在 `--scroll`（触发懒加载后）用 `networkidle`。微信保留 `networkidle`，因为图片懒加载需要它。如果 `domcontentloaded` 仍失败，会自动回退到 `load`。这样阮一峰博客的抓取从超时变成 ~3s 成功。
