#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站 本地扫码登录助手

为什么需要它：B站 对 Cloudflare / 机房出口 IP 做了整站风控（返回 412
request was banned），并且不允许第三方域名跨域调用登录接口，所以二维码
只能在你自己的浏览器里生成。

用法（在项目根目录执行）：

    python scripts/bili_login.py

流程：
    1. 脚本打开一个真实的 Chrome / Edge 窗口，停在 B站 登录页
    2. 你用 B站 App 扫码并在手机上确认
    3. 脚本通过 Playwright 自动导出全部 Cookie（含 httpOnly 的 SESSDATA）
    4. 脚本登录平台接口，把 Cookie 加密保存到你的账号
    全程不需要复制任何 Cookie。

可选参数：
    --server URL      平台地址，默认 https://pere.ygtxl.dpdns.org
    --username NAME   平台用户名（不填会交互式询问）
    --password PASS   平台密码（不填会交互式询问）
    --token TOKEN     直接提供平台 JWT，跳过账号密码登录
    --timeout SECONDS 等待扫码的超时时间，默认 300 秒
    --check           只检查平台登录与凭据状态，不打开浏览器
"""

import argparse
import getpass
import json
import sys
import time

# Windows 控制台默认 GBK，直接输出 emoji/中文会抛 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

DEFAULT_SERVER = "https://pere.ygtxl.dpdns.org"
BILI_LOGIN_URL = "https://passport.bilibili.com/login"
BILI_HOME_URL = "https://www.bilibili.com/"
BILI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"


# --------------------------------------------------------------------------
# 平台 API
# --------------------------------------------------------------------------

def platform_login(server: str, username: str, password: str) -> str:
    """用账号密码换取平台 JWT。"""
    import requests

    url = f"{server}/api/v1/auth/login"
    try:
        resp = requests.post(url, json={"username": username, "password": password}, timeout=20)
    except requests.exceptions.SSLError as exc:
        raise SystemExit(f"❌ 连接平台失败（SSL 证书错误）：{exc}\n   如果公司网络有代理拦截，请先处理证书后重试。")
    except requests.exceptions.RequestException as exc:
        raise SystemExit(f"❌ 连接平台失败：{exc}")

    try:
        body = resp.json()
    except ValueError:
        raise SystemExit(f"❌ 平台返回非 JSON（HTTP {resp.status_code}）：{resp.text[:200]}")

    data = body.get("data") or {}
    token = data.get("token")
    if resp.status_code != 200 or not token:
        raise SystemExit(f"❌ 平台登录失败：{body.get('msg') or resp.status_code}")

    print(f"✅ 平台登录成功：{data.get('username', username)}（{data.get('role', '')}）")
    return token


def get_credential_status(server: str, token: str) -> dict:
    import requests

    resp = requests.get(
        f"{server}/api/v1/bilibili/credentials",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    body = resp.json()
    if resp.status_code != 200:
        raise SystemExit(f"❌ 获取凭据状态失败：{body.get('msg') or resp.status_code}")
    return body.get("data") or {}


def save_credentials(server: str, token: str, cookies: list) -> dict:
    import requests

    payload = {"cookies": json.dumps(cookies, ensure_ascii=False)}
    resp = requests.post(
        f"{server}/api/v1/bilibili/credentials",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    try:
        body = resp.json()
    except ValueError:
        raise SystemExit(f"❌ 平台返回非 JSON（HTTP {resp.status_code}）：{resp.text[:200]}")

    if resp.status_code != 200:
        raise SystemExit(f"❌ 保存凭据失败：{body.get('msg') or resp.status_code}")
    return body.get("data") or {}


# --------------------------------------------------------------------------
# 浏览器扫码
# --------------------------------------------------------------------------

def normalize_cookies(raw_cookies: list) -> list:
    """把 Playwright 的 cookie 结构转成平台/CI 使用的格式。"""
    cookies = []
    for c in raw_cookies:
        domain = c.get("domain") or ""
        if "bilibili" not in domain and "biligame" not in domain:
            continue
        if not c.get("name") or c.get("value") in (None, ""):
            continue

        same_site = c.get("sameSite") or "Lax"
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"

        item = {
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path") or "/",
            "secure": bool(c.get("secure", True)),
            "httpOnly": bool(c.get("httpOnly", False)),
            "sameSite": same_site,
        }

        # Playwright 用 expires（秒，-1 表示会话 Cookie）
        expires = c.get("expires")
        if isinstance(expires, (int, float)) and expires > 0:
            item["expirationDate"] = int(expires)

        cookies.append(item)
    return cookies


def launch_browser(playwright):
    """优先使用本机 Chrome / Edge，退回 Playwright 自带 Chromium。"""
    errors = []
    for kwargs in (
        {"channel": "chrome", "headless": False},
        {"channel": "msedge", "headless": False},
        {"headless": False},
    ):
        try:
            return playwright.chromium.launch(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 逐个降级尝试
            errors.append(f"{kwargs.get('channel', 'chromium')}: {exc}")

    raise SystemExit(
        "❌ 无法启动浏览器。请确认已安装 Chrome/Edge，或执行：\n"
        "   python -m playwright install chromium\n"
        "   详情：\n   " + "\n   ".join(errors)
    )


def wait_for_login(context, timeout: int) -> list:
    """等待用户扫码，直到出现 SESSDATA + DedeUserID。"""
    deadline = time.time() + timeout
    last_hint = 0.0
    scanned_hint = False

    while time.time() < deadline:
        raw = context.cookies()
        names = {c["name"] for c in raw}

        if "SESSDATA" in names and "DedeUserID" in names:
            # 登录成功的瞬间 Cookie 还在陆续写入，稍等再完整导出
            time.sleep(1.5)
            return context.cookies()

        # 已扫码但还没确认时，B站 会先写入一些非登录态 Cookie，这里不做强判断，
        # 只按时间给出进度提示，避免误报。
        now = time.time()
        if now - last_hint > 15:
            remaining = int(deadline - now)
            print(f"⏳ 等待扫码…（剩余 {remaining}s）")
            last_hint = now

        time.sleep(1)

    raise SystemExit("⌛ 等待超时，未检测到登录成功。请重新运行脚本后尽快扫码。")


def fetch_bili_profile(page) -> dict:
    """借用已登录的页面读取 B站 用户信息，便于确认登录的是哪个账号。"""
    try:
        data = page.evaluate(
            "async () => {"
            f"  const r = await fetch('{BILI_NAV_API}', {{ credentials: 'include' }});"
            "  return await r.json();"
            "}"
        )
        if isinstance(data, dict) and data.get("code") == 0:
            return data.get("data") or {}
    except Exception:  # noqa: BLE001 - 仅用于展示，失败不影响主流程
        pass
    return {}


def run_browser_login(timeout: int) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "❌ 未安装 Playwright。请先执行：\n"
            "   pip install playwright\n"
            "   python -m playwright install chromium"
        )

    print("🌐 正在启动浏览器，请稍候…")
    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        context = browser.new_context(
            viewport={"width": 1280, "height": 860},
            locale="zh-CN",
        )
        page = context.new_page()

        try:
            page.goto(BILI_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            print("\n📱 请在弹出的浏览器窗口中用 B站 App 扫码，并在手机上点击确认。")
            print("   （登录成功后窗口会自动关闭）\n")

            raw_cookies = wait_for_login(context, timeout)

            profile = fetch_bili_profile(page)
            uname = profile.get("uname")
            if uname:
                print(f"✅ B站 登录成功：{uname}（UID {profile.get('mid')}）")
            else:
                print("✅ B站 登录成功（已获取登录 Cookie）")

            cookies = normalize_cookies(raw_cookies)
            if not any(c["name"] == "SESSDATA" for c in cookies):
                raise SystemExit("❌ 未获取到 SESSDATA，登录可能未完成，请重试。")

            print(f"🍪 已导出 {len(cookies)} 个 B站 Cookie")
            return cookies
        finally:
            context.close()
            browser.close()


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="B站 本地扫码登录助手（自动抓取 Cookie 并保存到平台）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--server", default=DEFAULT_SERVER, help="平台地址（默认生产环境）")
    parser.add_argument("--username", help="平台用户名")
    parser.add_argument("--password", help="平台密码")
    parser.add_argument("--token", help="平台 JWT（提供后跳过账号密码登录）")
    parser.add_argument("--timeout", type=int, default=300, help="等待扫码的超时秒数（默认 300）")
    parser.add_argument("--check", action="store_true", help="只检查平台登录与凭据状态")
    args = parser.parse_args()

    server = args.server.rstrip("/")

    # 1. 平台认证
    token = args.token
    if not token:
        username = args.username or input("平台用户名: ").strip()
        password = args.password or getpass.getpass("平台密码: ")
        token = platform_login(server, username, password)

    # 2. --check 模式
    if args.check:
        status = get_credential_status(server, token)
        if status.get("configured"):
            print(
                "✅ 当前账号已配置 B站 凭据"
                f"（SESSDATA={status.get('hasSessdata')}, bili_jct={status.get('hasBiliJct')}）"
            )
        else:
            print("ℹ️ 当前账号尚未配置 B站 凭据，运行本脚本扫码即可完成。")
        return 0

    # 3. 扫码 + 导出 Cookie
    cookies = run_browser_login(args.timeout)

    # 4. 上报平台
    print(f"📤 正在把凭据保存到 {server} …")
    status = save_credentials(server, token, cookies)

    print("\n🎉 完成！B站 登录凭据已加密保存到你的账号。")
    print(
        f"   凭据状态：SESSDATA={status.get('hasSessdata')}, "
        f"bili_jct={status.get('hasBiliJct')}"
    )
    print("   回到设置页点一下「刷新状态」即可看到「已登录」。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️ 已取消。")
        sys.exit(130)