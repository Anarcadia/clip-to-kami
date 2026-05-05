#!/usr/bin/env python3
"""
clip-to-kami: Convert WeChat articles, web pages, and local files to Kami-styled PDFs.

Usage:
    python convert.py <url_or_filepath> [--output <path>] [--title <title>] [--author <author>]
"""

import argparse
import os
import re
import sys
import tempfile
import zipfile
import html as html_module
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import platform
if platform.system() == "Darwin":
    # Apple Silicon → /opt/homebrew/lib; Intel Mac → /usr/local/lib
    _homebrew_lib = "/opt/homebrew/lib"
    if not Path(_homebrew_lib).exists():
        _homebrew_lib = "/usr/local/lib"
    if Path(_homebrew_lib).exists():
        _current_dyld = os.environ.get("DYLD_LIBRARY_PATH", "")
        if _homebrew_lib not in _current_dyld:
            os.environ["DYLD_LIBRARY_PATH"] = f"{_homebrew_lib}:{_current_dyld}" if _current_dyld else _homebrew_lib

try:
    from bs4 import BeautifulSoup, NavigableString
except ImportError:
    print("ERROR: beautifulsoup4 is required. Run: pip install beautifulsoup4")
    sys.exit(1)


# ── WeChat helpers ───────────────────────────────────────────────

def extract_wechat_publish_time(html: str) -> str:
    """Extract publish time from WeChat script tags (create_time JS variable)."""
    m = re.search(r"create_time\s*:\s*JsDecode\('([^']+)'\)", html)
    if not m:
        m = re.search(r"create_time\s*:\s*'(\d+)'", html)
    if m:
        try:
            ts = int(m.group(1))
            if ts > 0:
                from datetime import timezone, timedelta
                tz = timezone(timedelta(hours=8))
                return datetime.fromtimestamp(ts, tz).strftime("%Y-%m-%d")
        except ValueError:
            return m.group(1)
    return ""


def _derive_referer(source_url: str) -> str:
    """Derive Referer header from source URL. WeChat gets special pinned origin."""
    if not source_url:
        return ""
    if "mp.weixin.qq.com" in source_url:
        return "https://mp.weixin.qq.com/"
    parsed = urlparse(source_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return ""


def localize_images(content_html: str, output_dir: Path, source_url: str = "") -> str:
    """Download article images locally, replace remote URLs with local paths.

    Works for any webpage. Dedupes by URL so repeated images download once.
    Uses Referer derived from source_url to bypass hotlink protection.
    """
    import urllib.request
    import hashlib
    from urllib.parse import urljoin

    soup = BeautifulSoup(content_html, "html.parser")
    img_dir = output_dir / "images"
    img_dir.mkdir(exist_ok=True)

    referer = _derive_referer(source_url)
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }
    if referer:
        headers["Referer"] = referer

    url_to_local: dict = {}  # dedupe cache
    downloaded, failed, skipped = 0, 0, 0

    for i, img in enumerate(soup.find_all("img")):
        src = (img.get("data-src") or img.get("src", "") or "").strip()
        if not src or src.startswith(("data:", "javascript:")):
            skipped += 1
            continue
        if src.startswith("//"):
            src = "https:" + src
        # Resolve relative URLs against source
        if source_url and not src.startswith(("http://", "https://")):
            src = urljoin(source_url, src)
        if not src.startswith(("http://", "https://")):
            # Fallback: bare host or relative path with no source_url base.
            # Force https:// so we at least try the download instead of dropping silently.
            src = "https://" + src.lstrip("/")

        if src in url_to_local:
            img["src"] = url_to_local[src]
            if img.get("data-src"):
                img["data-src"] = url_to_local[src]
            continue

        ext_match = re.search(r"wx_fmt=(\w+)", src) or re.search(r"\.(\w{3,4})(?:\?|$)", src)
        ext = (ext_match.group(1) if ext_match else "png").lower()
        if ext not in {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"}:
            ext = "png"

        url_hash = hashlib.md5(src.encode("utf-8")).hexdigest()[:10]
        filename = f"img_{i+1:03d}_{url_hash}.{ext}"
        filepath = img_dir / filename

        try:
            req = urllib.request.Request(src, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                filepath.write_bytes(resp.read())
            local_path = str(filepath)
            url_to_local[src] = local_path
            img["src"] = local_path
            if img.get("data-src"):
                img["data-src"] = local_path
            downloaded += 1
        except Exception as e:
            print(f"  WARNING: Failed to download image {i+1}: {e}")
            failed += 1

    print(f"  Images: {downloaded} downloaded, {failed} failed, {skipped} skipped")
    return str(soup)


# Backwards-compat alias
download_wechat_images = localize_images


# ── Playwright fetch ──────────────────────────────────────────────

def _detect_cloudflare_challenge(title: str, html: str) -> bool:
    """Detect Cloudflare / bot-check interstitial pages."""
    if not title and not html:
        return False
    markers = [
        "Just a moment",
        "Checking your browser",
        "cf-browser-verification",
        "cf-challenge-running",
        "Attention Required",
    ]
    t = (title or "").lower()
    h = (html or "")[:4000].lower()  # only scan head
    return any(m.lower() in t or m.lower() in h for m in markers)


def fetch_with_playwright(
    url: str,
    wait_selector: str = None,
    scroll: bool = False,
    timeout: int = 30,
    use_stealth: bool = True,
) -> dict:
    """Fetch a URL using Playwright.

    Args:
        url: target URL
        wait_selector: optional CSS selector to wait for after page load (SPA helper)
        scroll: if True, scroll to bottom to trigger lazy-loading
        timeout: seconds for navigation/selector timeouts
        use_stealth: apply playwright-stealth to hide webdriver fingerprint
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright is required for URL fetching. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    timeout_ms = timeout * 1000

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="zh-CN",
        )

        if use_stealth:
            try:
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(context)
            except ImportError:
                print("  NOTE: playwright-stealth not installed; proceeding without stealth.")
            except Exception as e:
                print(f"  NOTE: stealth init failed ({e}); proceeding without stealth.")

        page = context.new_page()
        # 对微信沿用 networkidle（图片懒加载需要它），其他站点用 domcontentloaded
        # 规避 analytics/websocket 导致 networkidle 永不到达
        initial_wait = "networkidle" if "mp.weixin.qq.com" in url else "domcontentloaded"
        try:
            page.goto(url, wait_until=initial_wait, timeout=timeout_ms)
        except Exception as e:
            print(f"  WARNING: initial goto ({initial_wait}) failed: {e}")
            print(f"  Falling back to 'load' wait strategy...")
            page.goto(url, wait_until="load", timeout=timeout_ms)

        if "mp.weixin.qq.com" in url:
            # Retry once on timeout
            for attempt in range(2):
                try:
                    page.wait_for_selector("#js_content", timeout=15000 if attempt == 0 else 25000)
                    break
                except Exception:
                    if attempt == 0:
                        print("WeChat content not loaded, retrying...")
                        page.reload(wait_until="networkidle")
                    else:
                        raise

            content_html = page.evaluate('() => document.querySelector("#js_content")?.innerHTML || ""')
            title = page.evaluate('''() =>
                (document.querySelector("#activity-name") || document.querySelector("#activity_name"))?.textContent?.trim() || ""
            ''')
            author = page.evaluate('() => document.querySelector("#js_name")?.textContent?.trim() || ""')
            date = page.evaluate('() => document.querySelector("#publish_time")?.textContent?.trim() || ""')

            if not date:
                full_html = page.content()
                date = extract_wechat_publish_time(full_html)

            full_page_html = None
        else:
            # Optional: wait for user-specified selector (helps SPAs)
            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except Exception as e:
                    print(f"  WARNING: wait_selector '{wait_selector}' not found within {timeout}s: {e}")
            else:
                page.wait_for_selector("body", timeout=min(timeout_ms, 10000))

            # Optional: scroll to trigger lazy-loading
            if scroll:
                try:
                    page.evaluate("""async () => {
                        await new Promise(resolve => {
                            let totalHeight = 0;
                            const distance = 400;
                            const timer = setInterval(() => {
                                window.scrollBy(0, distance);
                                totalHeight += distance;
                                if (totalHeight >= document.body.scrollHeight) {
                                    clearInterval(timer);
                                    resolve();
                                }
                            }, 120);
                        });
                    }""")
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception as e:
                    print(f"  WARNING: scroll failed: {e}")

            # Grab the FULL page HTML — let the extractor stage pick the article
            full_page_html = page.content()
            title = page.title() or ""
            author = ""
            date = ""

            # Cloudflare / bot-check detection
            if _detect_cloudflare_challenge(title, full_page_html):
                print("  WARNING: Cloudflare / bot challenge detected. Output will likely be empty or the challenge page.")

            # Initial content — extractor stage (called from main) will refine
            content_html = full_page_html

        context.close()
        browser.close()

        return {
            "title": title,
            "author": author,
            "date": date,
            "html": content_html,
            "full_html": full_page_html,  # preserved for extractor stage
            "source": url,
        }


# ── Article extractor (generic pages) ─────────────────────────────

def _extract_with_selector_cascade(full_html: str) -> str:
    """Legacy CSS selector cascade — keeps old behavior as fallback."""
    soup = BeautifulSoup(full_html, "html.parser")
    for selector in ["article", ".article-content", ".post-content", "main", ".content"]:
        node = soup.select_one(selector)
        if node:
            return node.decode_contents()
    body = soup.find("body")
    return body.decode_contents() if body else full_html


def _extract_with_readability(full_html: str) -> tuple:
    """Return (content_html, title) via readability-lxml. Raises on failure."""
    from readability import Document
    doc = Document(full_html)
    summary = doc.summary(html_partial=True) or ""
    title = ""
    try:
        title = doc.short_title() or doc.title() or ""
    except Exception:
        pass
    return summary, title


def extract_article(full_html: str, strategy: str = "auto", raw_selector: str = None) -> tuple:
    """Extract article body HTML from a full web page.

    strategy:
        auto        → readability first, fallback to selector cascade
        readability → readability only
        selector    → CSS selector cascade only (legacy)
        raw         → use raw_selector (required)

    Returns (content_html, extracted_title). title may be empty.
    """
    if not full_html:
        return "", ""

    if strategy == "raw":
        if not raw_selector:
            print("  WARNING: --extractor raw requires --raw-selector; falling back to auto.")
            strategy = "auto"
        else:
            soup = BeautifulSoup(full_html, "html.parser")
            node = soup.select_one(raw_selector)
            if node:
                return node.decode_contents(), ""
            print(f"  WARNING: raw_selector '{raw_selector}' not found; falling back to auto.")
            strategy = "auto"

    if strategy in ("auto", "readability"):
        try:
            content, title = _extract_with_readability(full_html)
            if len(BeautifulSoup(content, "html.parser").get_text(strip=True)) >= 200:
                print(f"  Extractor: readability ({len(content)} chars)")
                return content, title
            if strategy == "readability":
                print("  WARNING: readability output too short; returning anyway.")
                return content, title
            print("  Extractor: readability output too short, falling back to selector cascade.")
        except ImportError:
            if strategy == "readability":
                print("ERROR: readability-lxml not installed. Run: pip install readability-lxml")
                sys.exit(1)
            print("  NOTE: readability-lxml not available; using selector cascade.")
        except Exception as e:
            if strategy == "readability":
                print(f"ERROR: readability failed: {e}")
                raise
            print(f"  NOTE: readability failed ({e}); using selector cascade.")

    content = _extract_with_selector_cascade(full_html)
    print(f"  Extractor: selector cascade ({len(content)} chars)")
    return content, ""


# ── XCrawl fetch (fallback) ───────────────────────────────────────

def fetch_with_xcrawl(url: str) -> dict:
    """Fetch a URL using XCrawl (for standard web pages)."""
    import subprocess
    import json

    config_path = Path.home() / ".xcrawl" / "config.json"
    if not config_path.exists():
        print("WARNING: XCrawl config not found. Using Playwright fallback.")
        return fetch_with_playwright(url)

    with open(config_path) as f:
        api_key = json.load(f).get("XCRAWL_API_KEY", "")

    if not api_key:
        print("WARNING: XCRAWL_API_KEY not set. Using Playwright fallback.")
        return fetch_with_playwright(url)

    cmd = [
        "curl", "-sS", "-X", "POST", "https://run.xcrawl.com/v1/scrape",
        "-H", "Content-Type: application/json",
        "-H", f"Authorization: Bearer {api_key}",
        "-d", json.dumps({"url": url, "mode": "sync", "output": {"formats": ["markdown", "links"]}}),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)

    # Convert markdown to simple HTML
    try:
        import markdown
        md_text = data.get("data", {}).get("markdown", "")
        html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    except ImportError:
        print("WARNING: python-markdown not installed. Raw text output.")
        html = f"<pre>{data.get('data', {}).get('markdown', '')}</pre>"

    return {
        "title": data.get("data", {}).get("metadata", {}).get("title", ""),
        "author": "",
        "date": "",
        "html": html,
        "source": url,
    }


# ── Local file read ───────────────────────────────────────────────

def read_local_file(filepath: str) -> dict:
    """Read a local Markdown or text file, parsing YAML frontmatter if present."""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    content = path.read_text(encoding="utf-8")

    # Parse and strip YAML frontmatter (---\n...\n---)
    metadata = {}
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if frontmatter_match:
        for line in frontmatter_match.group(1).splitlines():
            if ':' in line:
                key, _, value = line.partition(':')
                metadata[key.strip().lower()] = value.strip().strip('"').strip("'")
        content = content[frontmatter_match.end():]

    # Resolve source URL from frontmatter, fallback to local path
    source_url = (
        metadata.get("url")
        or metadata.get("source")
        or metadata.get("sourceurl")
        or metadata.get("source_url")
        or metadata.get("original_url")
        or metadata.get("link")
        or str(path)
    )

    # Convert markdown to HTML if needed
    if path.suffix.lower() in [".md", ".markdown"]:
        try:
            import markdown
            html = markdown.markdown(content, extensions=["tables", "fenced_code", "nl2br"])
        except ImportError:
            print("WARNING: python-markdown not installed. Install with: pip install markdown")
            html = f"<pre>{html_module.escape(content)}</pre>"
    else:
        # Plain text: wrap paragraphs
        paragraphs = [f"<p>{html_module.escape(p)}</p>" for p in content.split("\n\n") if p.strip()]
        html = "\n".join(paragraphs)

    return {
        "title": metadata.get("title") or path.stem,
        "author": metadata.get("author") or metadata.get("sourceauthor") or "",
        "date": metadata.get("date") or metadata.get("sourcedate") or "",
        "html": html,
        "source": source_url,
    }


# ── EPUB processing ───────────────────────────────────────────────

NSMAP = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "nav": "http://www.w3.org/1999/xhtml",
}


def _ns(tag: str) -> str:
    if ":" in tag:
        prefix, name = tag.split(":", 1)
        return f"{{{NSMAP.get(prefix, '')}}}{name}"
    return tag


def _tag_name(elem) -> str:
    tag = elem.tag
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def find_opf_path(container_xml: str) -> str:
    root = ET.fromstring(container_xml)
    for rootfile in root.iter():
        if rootfile.tag.endswith("rootfile"):
            path = rootfile.get("full-path", "")
            if path:
                return path
    raise ValueError("Cannot find OPF path in container.xml")


def parse_opf(opf_xml: str) -> dict:
    root = ET.fromstring(opf_xml)

    metadata = {}
    meta_elem = root.find(_ns("opf:metadata"))
    if meta_elem is not None:
        for child in meta_elem:
            tag = child.tag
            if tag.startswith("{http://purl.org/dc/elements/1.1/}"):
                key = tag.split("}", 1)[1]
                val = (child.text or "").strip()
                if val:
                    if key in metadata:
                        if isinstance(metadata[key], list):
                            metadata[key].append(val)
                        else:
                            metadata[key] = [metadata[key], val]
                    else:
                        metadata[key] = val

    manifest = {}
    manifest_elem = root.find(_ns("opf:manifest"))
    if manifest_elem is not None:
        for item in manifest_elem.findall(_ns("opf:item")):
            item_id = item.get("id", "")
            href = item.get("href", "")
            media_type = item.get("media-type", "")
            if item_id and href:
                manifest[item_id] = {"href": href, "media_type": media_type}

    spine = []
    spine_elem = root.find(_ns("opf:spine"))
    if spine_elem is not None:
        for itemref in spine_elem.findall(_ns("opf:itemref")):
            ref_id = itemref.get("idref", "")
            if ref_id:
                spine.append(ref_id)

    return {"metadata": metadata, "manifest": manifest, "spine": spine}


def parse_ncx_toc(ncx_xml: str) -> dict:
    root = ET.fromstring(ncx_xml)
    navmap = {}

    def walk_navpoints(parent, depth=0):
        for child in parent:
            if _tag_name(child) != "navPoint":
                continue
            nav_id = child.get("id", "")
            play_order = child.get("playOrder", "")
            label = ""
            src = ""
            for sub in child:
                tn = _tag_name(sub)
                if tn == "navLabel":
                    for text_elem in sub:
                        if _tag_name(text_elem) == "text" and text_elem.text:
                            label = text_elem.text.strip()
                elif tn == "content":
                    src = sub.get("src", "")
            navmap[nav_id] = {"label": label, "src": src, "playOrder": play_order, "depth": depth}
            walk_navpoints(child, depth + 1)

    for child in root:
        if _tag_name(child) == "navMap":
            walk_navpoints(child)
            break
    return navmap


def resolve_relative_path(base: str, href: str) -> str:
    if not href:
        return base
    base_dir = base.rsplit("/", 1)[0] if "/" in base else ""
    if base_dir:
        return f"{base_dir}/{href}"
    return href


def parse_epub(epub_path: str) -> dict:
    """Parse an EPUB file and return metadata + ordered chapters + images."""
    with zipfile.ZipFile(epub_path, "r") as zf:
        namelist = zf.namelist()

        if "META-INF/container.xml" not in namelist:
            raise ValueError("Invalid EPUB: missing META-INF/container.xml")
        container_xml = zf.read("META-INF/container.xml").decode("utf-8")
        opf_path = find_opf_path(container_xml)

        opf_xml = zf.read(opf_path).decode("utf-8")
        opf_data = parse_opf(opf_xml)
        manifest = opf_data["manifest"]
        spine = opf_data["spine"]

        toc_map = {}
        spine_elem = ET.fromstring(opf_xml).find(_ns("opf:spine"))
        toc_id = spine_elem.get("toc", "") if spine_elem is not None else ""
        if toc_id and toc_id in manifest:
            ncx_path = resolve_relative_path(opf_path, manifest[toc_id]["href"])
            if ncx_path in namelist:
                ncx_xml = zf.read(ncx_path).decode("utf-8")
                toc_map = parse_ncx_toc(ncx_xml)

        chapters = []
        for item_id in spine:
            if item_id not in manifest:
                continue
            item = manifest[item_id]
            href = item["href"]
            media_type = item["media_type"]
            if media_type not in ("application/xhtml+xml", "text/html"):
                continue

            full_path = resolve_relative_path(opf_path, href)
            if full_path not in namelist:
                print(f"  WARNING: chapter '{full_path}' not found in EPUB")
                continue

            chapter_html = zf.read(full_path).decode("utf-8")
            title = ""
            for nav_info in toc_map.values():
                nav_src = nav_info.get("src", "")
                nav_base = nav_src.split("#")[0] if nav_src else ""
                if nav_base == href:
                    title = nav_info.get("label", "")
                    break
            if not title:
                soup = BeautifulSoup(chapter_html, "html.parser")
                title_tag = soup.find("title")
                if title_tag and title_tag.string:
                    title = title_tag.string.strip()
                if not title:
                    h1 = soup.find("h1")
                    if h1:
                        title = h1.get_text(strip=True)

            chapters.append((item_id, title, chapter_html))

        images = {}
        for item_id, item in manifest.items():
            mt = item["media_type"]
            if mt and mt.startswith("image/"):
                full_path = resolve_relative_path(opf_path, item["href"])
                if full_path in namelist:
                    images[full_path] = zf.read(full_path)

        return {
            "metadata": opf_data["metadata"],
            "chapters": chapters,
            "images": images,
            "opf_path": opf_path,
            "manifest": manifest,
        }


def _generate_unique_id(base: str, used: set) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]", "_", base)[:40]
    if base not in used:
        used.add(base)
        return base
    i = 1
    while f"{base}_{i}" in used:
        i += 1
    uid = f"{base}_{i}"
    used.add(uid)
    return uid


def merge_chapters(chapters: list, opf_path: str, manifest: dict) -> tuple:
    """Merge chapter HTMLs into a single body string with anchored sections."""
    used_ids = set()
    id_remap = {}
    body_parts = []

    for idx, (item_id, title, html) in enumerate(chapters):
        soup = BeautifulSoup(html, "html.parser")

        for link in soup.find_all("link", rel="stylesheet"):
            link.decompose()
        for style in soup.find_all("style"):
            style.decompose()

        item_href = manifest.get(item_id, {}).get("href", "")

        for elem in soup.find_all(id=True):
            old_id = elem.get("id", "")
            if old_id:
                new_id = _generate_unique_id(f"ch{idx}_{old_id}", used_ids)
                id_remap[(item_href, old_id)] = new_id
                elem["id"] = new_id

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("http://") or href.startswith("https://"):
                continue
            if href.startswith("#"):
                old_id = href[1:]
                key = (item_href, old_id)
                if key in id_remap:
                    a["href"] = f"#{id_remap[key]}"
                else:
                    a["href"] = f"#ch{idx}_{old_id}"
            elif "#" in href:
                other_file, anchor = href.split("#", 1)
                key = (other_file, anchor)
                if key in id_remap:
                    a["href"] = f"#{id_remap[key]}"
                else:
                    resolved = resolve_relative_path(item_href, other_file)
                    key2 = (resolved, anchor)
                    if key2 in id_remap:
                        a["href"] = f"#{id_remap[key2]}"
                    else:
                        a.unwrap()
            else:
                a.unwrap()

        for img in soup.find_all("img", src=True):
            src = img["src"]
            if src.startswith("http://") or src.startswith("https://"):
                continue
            resolved = resolve_relative_path(item_href, src)
            full_resolved = resolve_relative_path(opf_path, resolved)
            img["src"] = full_resolved
            if img.get("data-src"):
                img["data-src"] = full_resolved

        body = soup.find("body")
        if body:
            if title:
                first_h1 = body.find("h1")
                if first_h1:
                    h1_text = first_h1.get_text(strip=True)
                    if h1_text == title or h1_text in title or title in h1_text:
                        first_h1.decompose()
            content = body.decode_contents()
        else:
            content = str(soup)

        chapter_anchor = _generate_unique_id(f"chapter_{idx}", used_ids)
        if title:
            section = f'<section id="{chapter_anchor}">\n  <h1 class="chapter-title">{html_module.escape(title)}</h1>\n{content}\n</section>\n'
        else:
            section = f'<section id="{chapter_anchor}">\n{content}\n</section>\n'
        body_parts.append(section)

    return "\n".join(body_parts), id_remap


def clean_merged_html(html: str) -> str:
    """Clean merged EPUB chapter HTML, preserving semantic structure."""
    soup = BeautifulSoup(html, "html.parser")

    for elem in soup.find_all(style=True):
        del elem["style"]

    for elem in soup.find_all(class_=True):
        classes = elem.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        keep = [c for c in classes if c not in (
            "calibre", "calibre1", "calibre2", "calibre3", "calibre4",
            "sgc-1", "sgc-2", "sgc-3", "sgc-4",
            "tx", "tx1", "tx2", "tx3",
            "p1", "p2", "p3", "p4",
            "s1", "s2", "s3",
            "c1", "c2", "c3",
            "color", "font",
            "center", "left", "right",
        )]
        if keep:
            elem["class"] = keep
        else:
            del elem["class"]

    for span in soup.find_all("span"):
        if not span.attrs and not span.get_text(strip=True):
            span.decompose()

    for div in soup.find_all("div"):
        if not div.attrs and not div.get_text(strip=True):
            div.decompose()

    for elem in soup.find_all(True):
        attrs_to_remove = []
        for attr in elem.attrs:
            if attr in ("data-uuid", "xml:lang", "xmlns", "xmlns:epub",
                        "epub:type", "role", "aria-label", "aria-hidden",
                        "onclick", "onload", "onerror"):
                if attr not in ("lang", "xml:lang"):
                    attrs_to_remove.append(attr)
            elif attr.startswith("data-") and attr != "data-src":
                attrs_to_remove.append(attr)
        for attr in attrs_to_remove:
            del elem[attr]

    for script in soup.find_all("script"):
        script.decompose()

    for img in soup.find_all("img"):
        src = img.get("src", "") or img.get("data-src", "")
        alt = img.get("alt", "")
        if src:
            parent = img.parent
            if parent and parent.name not in ("figure", "a"):
                figure = soup.new_tag("figure")
                img.wrap(figure)
                if alt:
                    figcaption = soup.new_tag("figcaption")
                    figcaption.string = alt
                    figure.append(figcaption)

    return str(soup)


def extract_epub_images(epub_data: dict, output_dir: Path) -> dict:
    """Extract EPUB images to output_dir/images/, return path map."""
    images = epub_data.get("images", {})
    if not images:
        return {}

    img_dir = output_dir / "images"
    img_dir.mkdir(exist_ok=True)

    path_map = {}
    for idx, (epub_path, data) in enumerate(images.items(), 1):
        ext = Path(epub_path).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"):
            ext = ".png"
        filename = f"img_{idx:04d}{ext}"
        local_path = img_dir / filename
        local_path.write_bytes(data)
        path_map[epub_path] = str(local_path)

    print(f"  Images: {len(path_map)} extracted")
    return path_map


def remap_image_paths(html: str, path_map: dict) -> str:
    """Replace EPUB-internal image paths with local file paths."""
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img", src=True):
        src = img["src"]
        if src in path_map:
            img["src"] = path_map[src]
        if img.get("data-src") and img["data-src"] in path_map:
            img["data-src"] = path_map[img["data-src"]]
    return str(soup)


# ── HTML cleaning ─────────────────────────────────────────────────

def clean_html(content_html: str, source_type: str = "wechat") -> str:
    """
    Clean raw HTML into Kami-compatible body content.

    PITFALL: Do NOT skip <section> elements just because they have no text.
    WeChat articles wrap images in <section> tags — skipping them removes
    all images from the output. Always recurse into children.

    PITFALL: WeChat images use data-src (original URL) and src (lazy-load placeholder).
    Prefer data-src. Skip SVG placeholder images entirely.
    """
    soup = BeautifulSoup(content_html, "html.parser")

    # Remove WeChat noise elements before processing
    for sel in ["script", "style", ".qr_code_pc", ".reward_area"]:
        for tag in soup.select(sel):
            tag.decompose()

    # Remove style and unnecessary data-* attributes, KEEP data-src for images
    for tag in soup.find_all(True):
        attrs_to_remove = [
            k for k in tag.attrs
            if k == "style"
            or (k.startswith("data-") and k != "data-src")
            or k in ["leaf", "nodeleaf", "type", "_width",
                     "data-report-img-idx", "data-fail",
                     "data-original-style", "data-index",
                     "data-aistatus", "data-imgfileid",
                     "data-ratio", "data-s", "data-w"]
        ]
        for attr in attrs_to_remove:
            del tag[attr]

    def process_element(elem):
        if isinstance(elem, NavigableString):
            text = str(elem)
            return html_module.escape(text) if text.strip() else ""

        # WeChat code block: extract code text, filter CSS counter noise
        if "code-snippet__fix" in (elem.get("class") or []):
            pre = elem.select_one("pre[data-lang]")
            lang = pre.get("data-lang", "") if pre else ""
            lines = []
            for code_tag in elem.find_all("code"):
                text = code_tag.get_text()
                if re.match(r"^[ce]?ounter\(line", text):
                    continue
                lines.append(text)
            code_text = "\n".join(lines) if lines else elem.get_text()
            escaped = html_module.escape(code_text)
            return f'<pre><code class="language-{html_module.escape(lang)}">{escaped}</code></pre>\n'

        if elem.name == "p":
            children = "".join(process_element(c) for c in elem.children).strip()
            return f"<p>{children}</p>\n" if children else ""

        # PITFALL: Never skip sections based on text content — they may contain only images
        elif elem.name == "section":
            return "".join(process_element(c) for c in elem.children)

        elif elem.name == "span":
            return "".join(process_element(c) for c in elem.children)

        elif elem.name == "strong":
            return f'<strong>{"".join(process_element(c) for c in elem.children)}</strong>'

        elif elem.name == "em":
            return f'<em>{"".join(process_element(c) for c in elem.children)}</em>'

        elif elem.name == "br":
            return "<br>"

        elif elem.name == "img":
            # PITFALL: Prefer data-src (original WeChat image) over src (lazy-loaded)
            src = elem.get("data-src", "") or elem.get("src", "")
            alt = elem.get("alt", "")
            # PITFALL: Skip SVG placeholder images used for lazy loading
            if src and not src.startswith("data:image/svg+xml"):
                return f'<figure><img src="{src}" alt="{html_module.escape(alt)}"><figcaption>{html_module.escape(alt)}</figcaption></figure>\n'
            return ""

        elif elem.name in ["ul", "ol"]:
            items = []
            for li in elem.find_all("li", recursive=False):
                item_text = "".join(process_element(c) for c in li.children).strip()
                if item_text:
                    items.append(f"<li>{item_text}</li>")
            if items:
                tag = "ol" if elem.name == "ol" else "ul"
                return f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>\n"
            return ""

        elif elem.name == "li":
            return "".join(process_element(c) for c in elem.children)

        elif elem.name == "a":
            href = elem.get("href", "")
            text = "".join(process_element(c) for c in elem.children)
            if href and text.strip():
                return f'<a href="{href}">{text}</a>'
            return text

        elif elem.name == "blockquote":
            text = "".join(process_element(c) for c in elem.children).strip()
            return f"<blockquote>\n{text}\n</blockquote>\n" if text else ""

        elif elem.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            text = "".join(process_element(c) for c in elem.children).strip()
            return f"<{elem.name}>{text}</{elem.name}>\n" if text else ""

        elif elem.name == "pre":
            text = elem.get_text()
            return f'<pre><code>{html_module.escape(text)}</code></pre>\n' if text.strip() else ""

        elif elem.name == "code":
            text = elem.get_text()
            return f'<code>{html_module.escape(text)}</code>'

        elif elem.name == "table":
            return str(elem)

        elif elem.name in ["figure", "figcaption"]:
            return "".join(process_element(c) for c in elem.children)

        else:
            return "".join(process_element(c) for c in elem.children)

    body_content = process_element(soup)
    body_content = re.sub(r"\n{3,}", "\n\n", body_content)
    return body_content


# ── Kami template filling ─────────────────────────────────────────

def fill_kami_template(
    body_content: str,
    title: str,
    author: str,
    date: str,
    source: str,
    template_path: str = None,
) -> str:
    """Fill content into Kami long-doc template."""

    if template_path is None:
        # Find Kami skill directory
        skill_dir = Path(__file__).parent.parent
        template_path = str(skill_dir / "assets" / "templates" / "long-doc.html")

        # Fallback to system Kami skill
        if not Path(template_path).exists():
            kami_paths = [
                Path.home() / ".claude" / "skills" / "kami" / "assets" / "templates" / "long-doc.html",
                Path.home() / ".claude" / "skills" / "kami" / "long-doc.html",
            ]
            for p in kami_paths:
                if p.exists():
                    template_path = str(p)
                    break

    with open(template_path) as f:
        template = f.read()

    subtitle = f"来源: {source}"

    final_html = template.replace("{{文档标题}}", title)
    final_html = final_html.replace("{{作者}}", author or "Kami")
    final_html = final_html.replace("{{摘要}}", subtitle)
    final_html = final_html.replace("{{关键词}}", "文档, 归档")
    final_html = final_html.replace(
        '{{EYEBROW · 如 "技术报告" / "年度总结" / "白皮书"}}',
        "网页归档" if source.startswith("http") else "文档归档",
    )
    final_html = final_html.replace(
        "{{文档主标题<br>可以两行}}",
        title.replace("。", "<br>") if len(title) > 20 else title,
    )
    final_html = final_html.replace(
        "{{副标题，一句话说清这份文档是什么 / 为谁而写}}",
        subtitle,
    )
    final_html = final_html.replace("{{作者 / 团队}}", author or "未知作者")
    final_html = final_html.replace("{{版本 V1.0}}  ·  {{日期 2026.04}}", date or "")
    final_html = final_html.replace("{{发布方 / 机构}}", "")

    # Replace TOC and template body with actual content
    pattern = r"(</section>\s*<!-- ═════════════ 目录 ═════════════ -->.*?)(</body>\s*</html>)"
    replacement = f"""
</section>

<!-- ═════════════ 正文内容 ═════════════ -->
<section>
  <div class="chapter-num">正文</div>
  <h1>{title}</h1>
{body_content}
</section>

\2"""

    final_html = re.sub(pattern, replacement, final_html, flags=re.DOTALL)
    return final_html


# ── Black-and-white theme ─────────────────────────────────────────

BW_COLOR_MAP = {
    "#f5f4ed": "#ffffff",   # parchment / @page background
    "#faf9f5": "#f5f5f5",   # ivory  → very light gray
    "#e8e6dc": "#d0d0d0",   # border → medium gray
    "#e5e3d8": "#cccccc",   # border-soft → light gray
    "#E4ECF5": "#e8e8e8",   # tag-bg → light gray (less blue)
}


def apply_bw_theme(html: str) -> str:
    """
    Replace parchment colors with white/gray for black-and-white printing.
    Brand color (#1B365D ink-blue) is kept — it renders as dark gray on B&W printers.
    """
    for old, new in BW_COLOR_MAP.items():
        html = html.replace(old, new)
    return html


# ── PDF generation ────────────────────────────────────────────────

def generate_pdf(html_content: str, output_path: str, font_dir: str = None) -> str:
    """
    Generate PDF using WeasyPrint.

    PITFALL: On macOS, WeasyPrint requires Homebrew libraries in DYLD_LIBRARY_PATH.
    If weasyprint import fails with "cannot load library", set (use $(brew --prefix)
    so it works on both Apple Silicon /opt/homebrew and Intel /usr/local):
        export DYLD_LIBRARY_PATH=$(brew --prefix)/lib:$DYLD_LIBRARY_PATH
    """
    try:
        from weasyprint import HTML
    except ImportError:
        print("ERROR: weasyprint is required. Run: pip install weasyprint")
        print("NOTE: On macOS, also run: brew install pango gdk-pixbuf cairo")
        sys.exit(1)
    except OSError as e:
        if "libgobject" in str(e).lower():
            print("ERROR: WeasyPrint cannot find system libraries.")
            print("On macOS with Homebrew, run one of (depending on architecture):")
            print("  Apple Silicon: export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH")
            print("  Intel Mac:     export DYLD_LIBRARY_PATH=/usr/local/lib:$DYLD_LIBRARY_PATH")
            print("  Or portably:   export DYLD_LIBRARY_PATH=$(brew --prefix)/lib:$DYLD_LIBRARY_PATH")
            sys.exit(1)
        raise

    # Create temp directory with fonts
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = Path(tmpdir) / "document.html"
        html_path.write_text(html_content, encoding="utf-8")

        # Copy fonts for local rendering
        # Prefer bundled fonts (always present in release); fall back to system
        # Kami skill in case the user has it installed and bundled fonts went missing.
        if font_dir is None:
            for font_src in [
                Path(__file__).parent.parent / "assets" / "fonts",
                Path.home() / ".claude" / "skills" / "kami" / "assets" / "fonts",
            ]:
                if font_src.exists():
                    font_dir = str(font_src)
                    break

        if font_dir:
            import shutil
            fonts_tmp = Path(tmpdir) / "fonts"
            fonts_tmp.mkdir()
            for font_file in Path(font_dir).glob("*.ttf"):
                shutil.copy(font_file, fonts_tmp)

        # Generate PDF
        HTML(str(html_path)).write_pdf(output_path)

    return output_path


# ── Main ──────────────────────────────────────────────────────────

def detect_input_type(input_str: str) -> str:
    """Detect input type: wechat / webpage / epub / local."""
    parsed = urlparse(input_str)
    if parsed.scheme in ("http", "https"):
        if "mp.weixin.qq.com" in parsed.netloc:
            return "wechat"
        return "webpage"
    if input_str.lower().endswith(".epub"):
        return "epub"
    return "local"


def create_output_dir(title: str) -> Path:
    """
    Create a timestamped folder under ~/Downloads/clip-to-kami/.
    Returns the folder path.
    """
    # Sanitize title for filesystem safety
    safe_title = re.sub(r'[^\w\s\-\u4e00-\u9fff]', '', title or 'untitled').strip()[:40]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    folder_name = f"{timestamp}_{safe_title}" if safe_title else timestamp

    base_dir = Path.home() / "Downloads" / "clip-to-kami"
    output_dir = base_dir / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def main():
    parser = argparse.ArgumentParser(description="Convert articles to Kami-styled PDF")
    parser.add_argument("input", help="URL or file path")
    parser.add_argument("-o", "--output", help="Output PDF path (default: auto-generated under ~/Downloads/clip-to-kami/)")
    parser.add_argument("-t", "--title", help="Override document title")
    parser.add_argument("-a", "--author", help="Override document author")
    parser.add_argument("--font-dir", help="Directory containing TsangerJinKai02 fonts")
    parser.add_argument("--template", help="Path to Kami HTML template")
    parser.add_argument("--no-html", action="store_true", help="Do not save the intermediate HTML file")
    parser.add_argument("--bw", action="store_true", help="同时生成黑白打印友好的纯白版本（-bw 后缀）")
    parser.add_argument("-s", "--source", help="Override source URL (shown on cover)")
    # New in Phase 1
    parser.add_argument("--extractor", choices=["auto", "readability", "selector", "raw"], default="auto",
                        help="Article body extraction strategy for generic web pages (default: auto)")
    parser.add_argument("--raw-selector", help="Manual CSS selector for article body (implies --extractor=raw)")
    parser.add_argument("--wait-selector", help="CSS selector to wait for after page load (SPA helper)")
    parser.add_argument("--scroll", action="store_true", help="Scroll to bottom to trigger lazy-loading")
    parser.add_argument("--timeout", type=int, default=30, help="Page navigation timeout in seconds (default: 30)")
    parser.add_argument("--no-stealth", action="store_true", help="Disable playwright-stealth (debugging)")
    parser.add_argument("--no-image-download", action="store_true", help="Skip image localization (keep remote URLs)")
    parser.add_argument("--use-xcrawl", action="store_true", help="Try XCrawl first for non-WeChat URLs (needs ~/.xcrawl/config.json)")
    args = parser.parse_args()

    # Auto-switch strategy when raw_selector is provided
    if args.raw_selector and args.extractor == "auto":
        args.extractor = "raw"

    input_type = detect_input_type(args.input)
    print(f"Detected input type: {input_type}")

    # EPUB has its own pipeline (parse → merge → clean → extract images),
    # bypassing fetch / clean_html / localize_images.
    if input_type == "epub":
        epub_path = Path(args.input)
        if not epub_path.exists():
            print(f"ERROR: File not found: {epub_path}")
            sys.exit(1)

        print(f"Parsing EPUB: {epub_path}")
        try:
            epub_data = parse_epub(str(epub_path))
        except Exception as e:
            print(f"ERROR: Failed to parse EPUB: {e}")
            sys.exit(1)

        chapters = epub_data["chapters"]
        if not chapters:
            print("ERROR: No readable chapters found in EPUB")
            sys.exit(1)
        print(f"  Chapters: {len(chapters)}")
        print(f"  Images: {len(epub_data.get('images', {}))}")

        meta = epub_data["metadata"]

        def _first(v):
            return v[0] if isinstance(v, list) and v else (v or "")

        title = args.title or _first(meta.get("title")) or epub_path.stem
        author = args.author or _first(meta.get("creator"))
        date = _first(meta.get("date"))
        source = args.source or epub_path.name

        print(f"  Title: {title}")
        print(f"  Author: {author}")

        print("Merging chapters...")
        merged_body, _ = merge_chapters(chapters, epub_data["opf_path"], epub_data["manifest"])
        print(f"  Merged: {len(merged_body)} chars")

        print("Cleaning HTML...")
        cleaned = clean_merged_html(merged_body)
        print(f"  Cleaned: {len(cleaned)} chars")

        if args.output:
            output_base = Path(args.output).with_suffix("")
            output_dir = output_base.parent
        else:
            output_dir = create_output_dir(title)
            safe_title = re.sub(r'[^\w\s\-一-鿿]', '', title or 'untitled').strip()[:40]
            output_base = output_dir / (safe_title or 'document')
        output_dir.mkdir(parents=True, exist_ok=True)

        if epub_data.get("images") and not args.no_image_download:
            print("Extracting images...")
            path_map = extract_epub_images(epub_data, output_dir)
            if path_map:
                cleaned = remap_image_paths(cleaned, path_map)

        html = fill_kami_template(
            body_content=cleaned,
            title=title or "Untitled",
            author=author,
            date=date,
            source=source,
            template_path=args.template,
        )

        if args.bw:
            kami_pdf = output_base.with_name(f"{output_base.name}-kami.pdf")
            bw_pdf = output_base.with_name(f"{output_base.name}-bw.pdf")
            generate_pdf(html, str(kami_pdf), font_dir=args.font_dir)
            print(f"PDF generated: {kami_pdf}")
            html_bw = apply_bw_theme(html)
            generate_pdf(html_bw, str(bw_pdf), font_dir=args.font_dir)
            print(f"PDF generated: {bw_pdf}")
            if not args.no_html:
                kami_pdf.with_suffix(".html").write_text(html, encoding="utf-8")
                bw_pdf.with_suffix(".html").write_text(html_bw, encoding="utf-8")
                print(f"HTML source saved: {kami_pdf.with_suffix('.html')}")
                print(f"HTML source saved: {bw_pdf.with_suffix('.html')}")
            print(f"All outputs in: {output_dir}")
            return str(kami_pdf)
        else:
            output_pdf = Path(args.output) if args.output else output_base.with_suffix(".pdf")
            generate_pdf(html, str(output_pdf), font_dir=args.font_dir)
            print(f"PDF generated: {output_pdf}")
            if not args.no_html:
                output_html = output_pdf.with_suffix(".html")
                output_html.write_text(html, encoding="utf-8")
                print(f"HTML source saved: {output_html}")
            print(f"All outputs in: {output_dir}")
            return str(output_pdf)

    # Fetch content
    if input_type == "wechat":
        data = fetch_with_playwright(
            args.input,
            timeout=args.timeout,
            use_stealth=not args.no_stealth,
        )
    elif input_type == "webpage":
        if args.use_xcrawl:
            try:
                data = fetch_with_xcrawl(args.input)
            except Exception:
                print("XCrawl failed, falling back to Playwright...")
                data = fetch_with_playwright(
                    args.input,
                    wait_selector=args.wait_selector,
                    scroll=args.scroll,
                    timeout=args.timeout,
                    use_stealth=not args.no_stealth,
                )
        else:
            data = fetch_with_playwright(
                args.input,
                wait_selector=args.wait_selector,
                scroll=args.scroll,
                timeout=args.timeout,
                use_stealth=not args.no_stealth,
            )

        # Extractor stage for generic web pages
        if data.get("full_html"):
            extracted_html, extracted_title = extract_article(
                data["full_html"],
                strategy=args.extractor,
                raw_selector=args.raw_selector,
            )
            if extracted_html:
                data["html"] = extracted_html
            if extracted_title and not data.get("title"):
                data["title"] = extracted_title
    else:
        data = read_local_file(args.input)

    # Overrides
    if args.title:
        data["title"] = args.title
    if args.author:
        data["author"] = args.author
    if args.source:
        data["source"] = args.source

    print(f"Title: {data['title']}")
    print(f"Author: {data['author']}")
    print(f"Content length: {len(data['html'])} chars")

    # Determine output path early (needed for image download)
    if args.output:
        output_base = Path(args.output).with_suffix("")
        output_dir = output_base.parent
    else:
        output_dir = create_output_dir(data["title"])
        safe_title = re.sub(r'[^\w\s\-\u4e00-\u9fff]', '', data["title"] or 'untitled').strip()[:40]
        output_base = output_dir / (safe_title or 'document')
    output_dir.mkdir(parents=True, exist_ok=True)

    # Localize images for all remote fetches (WeChat + general webpages)
    if input_type in ("wechat", "webpage") and not args.no_image_download:
        print("Downloading images...")
        data["html"] = localize_images(
            data["html"],
            output_dir,
            source_url=data.get("source", args.input),
        )

    # Clean HTML
    body_content = clean_html(data["html"], source_type=input_type)
    print(f"Cleaned content: {len(body_content)} chars")

    # Fill template
    html = fill_kami_template(
        body_content=body_content,
        title=data["title"] or "Untitled",
        author=data["author"],
        date=data["date"],
        source=data["source"],
        template_path=args.template,
    )

    if args.bw:
        # Generate both Kami (parchment) and BW (white) versions
        kami_pdf = output_base.with_name(f"{output_base.name}-kami.pdf")
        bw_pdf = output_base.with_name(f"{output_base.name}-bw.pdf")

        generate_pdf(html, str(kami_pdf), font_dir=args.font_dir)
        print(f"PDF generated: {kami_pdf}")

        html_bw = apply_bw_theme(html)
        generate_pdf(html_bw, str(bw_pdf), font_dir=args.font_dir)
        print(f"PDF generated: {bw_pdf}")

        if not args.no_html:
            kami_html = kami_pdf.with_suffix(".html")
            bw_html = bw_pdf.with_suffix(".html")
            kami_html.write_text(html, encoding="utf-8")
            bw_html.write_text(html_bw, encoding="utf-8")
            print(f"HTML source saved: {kami_html}")
            print(f"HTML source saved: {bw_html}")

        print(f"All outputs in: {output_dir}")
        return str(kami_pdf)
    else:
        # Single version (parchment) — original behavior
        if args.output:
            output_pdf = Path(args.output)
        else:
            output_pdf = output_base.with_suffix(".pdf")

        generate_pdf(html, str(output_pdf), font_dir=args.font_dir)
        print(f"PDF generated: {output_pdf}")

        if not args.no_html:
            output_html = output_pdf.with_suffix(".html")
            output_html.write_text(html, encoding="utf-8")
            print(f"HTML source saved: {output_html}")

        print(f"All outputs in: {output_dir}")
        return str(output_pdf)


if __name__ == "__main__":
    main()
