#!/usr/bin/env python3
"""clip-to-kami 环境自检工具

检查依赖完整性并给出修复建议。退出码 0 表示全部通过，非 0 表示有缺失项。
用法：python3 scripts/doctor.py
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# macOS: WeasyPrint 依赖 Homebrew 动态库。必须在任何 weasyprint 相关 import 前设置
if platform.system() == "Darwin":
    _brew_lib = "/opt/homebrew/lib"
    if not Path(_brew_lib).exists():
        _brew_lib = "/usr/local/lib"
    os.environ["DYLD_LIBRARY_PATH"] = (
        f"{_brew_lib}:" + os.environ.get("DYLD_LIBRARY_PATH", "")
    )

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {GREEN}✅{RESET} {msg}")


def _fail(msg: str, fix: str = "") -> None:
    print(f"  {RED}❌{RESET} {msg}")
    if fix:
        print(f"     {CYAN}→ 修复：{fix}{RESET}")


def _warn(msg: str, fix: str = "") -> None:
    print(f"  {YELLOW}⚠️{RESET}  {msg}")
    if fix:
        print(f"     {CYAN}→ 建议：{fix}{RESET}")


def _section(title: str) -> None:
    print(f"\n{BOLD}{title}{RESET}")


class Report:
    def __init__(self) -> None:
        self.errors = 0
        self.warnings = 0

    def ok(self, msg: str) -> None:
        _ok(msg)

    def fail(self, msg: str, fix: str = "") -> None:
        _fail(msg, fix)
        self.errors += 1

    def warn(self, msg: str, fix: str = "") -> None:
        _warn(msg, fix)
        self.warnings += 1


def check_python(r: Report) -> None:
    _section("Python 运行环境")
    ver = sys.version_info
    if (ver.major, ver.minor) >= (3, 9):
        r.ok(f"Python {ver.major}.{ver.minor}.{ver.micro}")
    else:
        r.fail(
            f"Python {ver.major}.{ver.minor}.{ver.micro} 过低，需要 ≥ 3.9",
            "安装 Python 3.9+（macOS 推荐 `brew install python@3.12`）",
        )


def check_pip_packages(r: Report) -> None:
    _section("Python 包依赖")
    packages = {
        "weasyprint": "PDF 渲染核心",
        "bs4": "HTML 解析（beautifulsoup4）",
        "markdown": "Markdown 转 HTML",
        "playwright": "浏览器自动化抓取",
        "readability": "正文提取（readability-lxml）",
        "playwright_stealth": "反爬增强",
    }
    missing = []
    for mod, desc in packages.items():
        try:
            __import__(mod)
            r.ok(f"{mod} —— {desc}")
        except ImportError:
            missing.append(mod)
            r.fail(f"{mod} 未安装 —— {desc}")
    if missing:
        print(
            f"     {CYAN}→ 一键修复：pip install -r requirements.txt{RESET}"
        )


def check_playwright_browser(r: Report) -> None:
    _section("Playwright Chromium 浏览器")
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            if path and Path(path).exists():
                r.ok(f"Chromium 已安装：{path}")
            else:
                r.fail(
                    "Chromium 可执行文件未找到",
                    "playwright install chromium",
                )
    except ImportError:
        r.warn("playwright 未安装，跳过浏览器检测", "pip install playwright")
    except Exception as e:
        r.fail(
            f"Playwright 检测失败：{e}",
            "playwright install chromium",
        )


def check_system_libs_macos(r: Report) -> None:
    _section("macOS 系统库（WeasyPrint 依赖）")
    if platform.system() != "Darwin":
        print(f"  {CYAN}(非 macOS，跳过){RESET}")
        return
    brew = shutil.which("brew")
    if not brew:
        r.fail(
            "Homebrew 未安装",
            "按 https://brew.sh 安装 Homebrew",
        )
        return
    r.ok(f"Homebrew: {brew}")
    required = ["pango", "gdk-pixbuf", "cairo"]
    try:
        out = subprocess.run(
            ["brew", "list", "--formula"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        installed = set(out.stdout.split())
        missing = [pkg for pkg in required if pkg not in installed]
        for pkg in required:
            if pkg in installed:
                r.ok(f"brew 包 {pkg}")
            else:
                r.fail(f"brew 包 {pkg} 未安装")
        if missing:
            print(
                f"     {CYAN}→ 修复：brew install {' '.join(missing)}{RESET}"
            )
    except Exception as e:
        r.warn(f"brew list 检查失败：{e}")


def check_dyld_path(r: Report) -> None:
    _section("动态链接器路径（macOS WeasyPrint 必需）")
    if platform.system() != "Darwin":
        print(f"  {CYAN}(非 macOS，跳过){RESET}")
        return
    homebrew_lib = Path("/opt/homebrew/lib")
    if not homebrew_lib.exists():
        homebrew_lib = Path("/usr/local/lib")
    if homebrew_lib.exists():
        r.ok(f"Homebrew 库目录存在：{homebrew_lib}")
    else:
        r.fail(
            "找不到 Homebrew 库目录（/opt/homebrew/lib 或 /usr/local/lib）",
            "brew install pango gdk-pixbuf cairo",
        )
        return
    dyld = os.environ.get("DYLD_LIBRARY_PATH", "")
    if str(homebrew_lib) in dyld:
        r.ok(f"DYLD_LIBRARY_PATH 已包含 {homebrew_lib}")
    else:
        r.warn(
            "DYLD_LIBRARY_PATH 未显式包含 Homebrew 库目录",
            f"convert.py 会自动设置，也可手动 export DYLD_LIBRARY_PATH={homebrew_lib}:$DYLD_LIBRARY_PATH",
        )


def check_weasyprint_smoke(r: Report) -> None:
    _section("WeasyPrint 冒烟测试")
    try:
        if platform.system() == "Darwin":
            os.environ["DYLD_LIBRARY_PATH"] = (
                "/opt/homebrew/lib:" + os.environ.get("DYLD_LIBRARY_PATH", "")
            )
        from weasyprint import HTML

        HTML(string="<p>doctor smoke test</p>").write_pdf(target=None)
        r.ok("WeasyPrint 可正常生成 PDF")
    except Exception as e:
        r.fail(
            f"WeasyPrint 调用失败：{type(e).__name__}: {e}",
            "确认 Homebrew 包齐全并设置 DYLD_LIBRARY_PATH",
        )


def check_optional(r: Report) -> None:
    _section("可选项（不影响主流程）")
    xcrawl_cfg = Path.home() / ".xcrawl" / "config.json"
    if xcrawl_cfg.exists():
        r.ok(f"XCrawl 配置已就绪：{xcrawl_cfg}")
    else:
        _warn(
            "XCrawl 未配置（可选，仅在强 JS 站点需要）",
            f"创建 {xcrawl_cfg}，内容 {{\"XCRAWL_API_KEY\": \"...\"}}",
        )
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    font_dirs = [
        project_root / "assets" / "fonts",
        Path.home() / ".claude" / "skills" / "kami" / "assets" / "fonts",
    ]
    font_found = any(
        (d / "TsangerJinKai02-W04.ttf").exists() for d in font_dirs
    )
    if font_found:
        r.ok("TsangerJinKai02 字体已就绪")
    else:
        _warn(
            "TsangerJinKai02 字体未找到（将回退到系统衬线字体）",
            "商业字体请自行获取，放至 assets/fonts/",
        )


def main() -> int:
    print(f"{BOLD}=== clip-to-kami 环境自检 ==={RESET}")
    print(f"操作系统：{platform.system()} {platform.release()}")
    print(f"工作目录：{Path.cwd()}")
    r = Report()
    check_python(r)
    check_pip_packages(r)
    check_playwright_browser(r)
    check_system_libs_macos(r)
    check_dyld_path(r)
    check_weasyprint_smoke(r)
    check_optional(r)
    print()
    if r.errors == 0:
        print(
            f"{BOLD}{GREEN}✓ 全部必要项通过{RESET}"
            + (f"（{r.warnings} 条警告）" if r.warnings else "")
        )
        return 0
    print(
        f"{BOLD}{RED}✗ {r.errors} 项失败{RESET}"
        + (f"，{r.warnings} 条警告" if r.warnings else "")
    )
    print(f"{CYAN}→ 按上方提示修复后重新运行 `python3 scripts/doctor.py`{RESET}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
