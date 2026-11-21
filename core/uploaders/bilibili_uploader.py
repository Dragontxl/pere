"""B站（哔哩哔哩）无头上传脚本

使用 Playwright 浏览器自动化完成 B站投稿页上传，参考 one_minute_recap
项目的 go-rod 实现，改用 Python + Playwright。

完整流程：
1. 从 R2 下载视频、封面、Cookie
2. 用 Agnes 从文章内容提炼简介和标签（不超过5个）
3. 启动无头浏览器，注入 Cookie，打开投稿页
4. 上传视频，**等待文件真正上传到 100%**（卡死/超时直接报错，避免假成功）
5. 上传封面 → 填标题/简介/标签 → 选 AI 声明/分区（在上传完成后填写，避免表单被重置）
6. 提交投稿，从投稿接口/创作中心接口获取 BV 号（个人空间轮询兜底）
7. 发送结果回调到后端

用法（CI 调用）：
    python -m core.uploaders.bilibili_uploader \
        --task-id <id> \
        --video-key <r2_key> \
        --cover-key <r2_key> \
        --cookies-key <r2_key> \
        --title <标题> \
        --article-content <文章内容> \
        --orientation <landscape|portrait> \
        --callback-url <url> \
        --callback-secret <secret> \
        --r2-bucket <bucket> \
        --r2-access-key-id <id> \
        --r2-secret-access-key <key> \
        --r2-endpoint <endpoint> \
        --agnes-api-key <key> \
        --agnes-base-url <url>
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

# ── R2 (S3-compatible) 下载 ─────────────────────────────────────────────


def download_from_r2(r2_key, dest_path, bucket, access_key_id, secret_access_key, endpoint):
    """从 R2 下载文件到本地（使用 boto3）"""
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=endpoint.rstrip("/"),
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )
    client.download_file(bucket, r2_key, dest_path)
    print(f"  📥 已从 R2 下载: {r2_key} -> {dest_path}")


# ── Agnes 提炼简介与标签 ────────────────────────────────────────────────


def extract_metadata(title, article_content, agnes_api_key, agnes_base_url):
    """用 Agnes 从文章内容提炼视频简介和标签

    Returns:
        (description, tags) — description 为 100-200 字简介，tags 为不超过 5 个标签的列表
    """
    from core.agnes_client import AgnesClient

    client = AgnesClient(base_url=agnes_base_url or "https://apihub.agnes-ai.com/v1", api_key=agnes_api_key)

    article_preview = article_content[:3000] if article_content else ""
    if not article_preview:
        article_preview = "（无文章内容，请基于标题生成简介和标签）"

    prompt = (
        f"你是一个视频内容编辑。根据以下文章标题和内容，生成视频投稿的简介和标签。\n\n"
        f"标题：{title}\n\n"
        f"文章内容：\n{article_preview}\n\n"
        f"要求：\n"
        f"1. 简介：100-200字，概括视频核心内容，语言简洁有吸引力，不要添加与内容无关的营销用语\n"
        f"2. 标签：从内容中提炼3-5个最相关的标签，每个标签2-8个字，不要使用过于宽泛的标签\n"
        f"3. 严格输出 JSON 格式，不要输出其他内容：\n"
        f'{{"description": "简介内容", "tags": ["标签1", "标签2", "标签3"]}}\n'
    )

    response = client.chat.completions.create(
        model="agnes-3.0-flash",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    raw = response.choices[0].message.content.strip()

    # 提取 JSON（模型可能输出 ```json ... ``` 包裹）
    if "```" in raw:
        lines = raw.split("\n")
        for line in lines:
            if line.strip().startswith("{"):
                raw = line.strip()
                break
        else:
            # 取最后一个完整 JSON 块
            raw = raw.split("```")[1] if raw.count("```") >= 2 else raw

    # 兜底：找第一个 { 到最后一个 }
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]

    data = json.loads(raw)
    description = str(data.get("description", "")).strip()
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip() for t in tags if str(t).strip()][:5]

    if not description:
        description = title  # 兜底：简介用标题
    if not tags:
        tags = [title]  # 兜底：标签用标题

    print(f"  📝 简介: {description[:80]}...")
    print(f"  🏷️ 标签: {', '.join(tags)}")
    return description, tags


# ── Playwright 浏览器自动化上传 ─────────────────────────────────────────


class BilibiliUploader:
    """B站无头上传器（Playwright 实现）"""

    UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame?page_from=creative_home_top_upload"
    SPACE_URL_TEMPLATE = "https://space.bilibili.com/{uid}/video"
    # 视频上传等待：总超时 20 分钟，连续 5 分钟无进度视为卡死
    UPLOAD_TIMEOUT = 20 * 60
    UPLOAD_STALL_TIMEOUT = 5 * 60

    def __init__(self, video_path, cover_path, cookies_path, title, description, tags, headless=True, work_dir=None):
        self.video_path = video_path
        self.cover_path = cover_path
        self.cookies_path = cookies_path
        self.title = title
        self.description = description
        self.tags = tags
        self.headless = headless
        self.work_dir = work_dir or "./bilibili_work"
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.submit_bvid = None
        self._upload_confirmed = False
        self._submit_api_responses = []

    def run(self):
        """执行上传，返回 (bvid, url) 或 (None, None)"""
        self._launch()
        try:
            self._inject_cookies(self.cookies_path)
            self._navigate()
            self._check_login()
            self._close_notification()
            self._upload_video()
            # 关键：等视频真正上传完成后再填表/上传封面/投稿。
            # 之前在上传进度 88-93% 时点击投稿，B站提示“等待视频上传完成后会自动提交”，
            # 随后上传卡死、页面表单被重置，导致封面和标题等元数据丢失。
            self._wait_for_upload_complete()
            self._handle_confirm_dialog()
            self._upload_cover()
            # 防御：若封面未落到表单上（页面重置/弹窗异常），重试一次
            if self.cover_path and os.path.exists(self.cover_path) and not self._cover_present(wait=5):
                print("  ⚠️ 表单未显示封面，重试上传封面...")
                self._upload_cover()
            self._fill_title()
            self._select_ai_declaration()
            self._select_district()
            self._fill_tags()
            self._fill_description()
            self._submit()
            bvid = self._wait_for_bvid()
            url = f"https://www.bilibili.com/video/{bvid}" if bvid else None
            return bvid, url
        finally:
            self._close()

    def _take_screenshot(self, name, full_page=False):
        """保存截图到工作目录（用于调试）"""
        try:
            import os
            os.makedirs(self.work_dir, exist_ok=True)
            path = os.path.join(self.work_dir, f"{name}.png")
            self.page.screenshot(path=path, full_page=full_page)
            print(f"  📸 截图已保存: {path}")
        except Exception as e:
            print(f"  ⚠️ 截图失败: {e}")

    def _launch(self):
        """启动无头浏览器"""
        from playwright.sync_api import sync_playwright

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--start-maximized",
                "--disable-background-networking",
                "--disable-popup-blocking",
            ],
        )
        self.context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self.page = self.context.new_page()
        # 反检测：隐藏 navigator.webdriver，避免被B站识别为自动化浏览器
        self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        # 监听投稿接口响应，直接拿 BV 号（比轮询个人空间更可靠）
        self.page.on("response", self._on_submit_response)
        print("  🚀 浏览器已启动")

    def _on_submit_response(self, response):
        """记录投稿接口响应（仅缓存对象，不在此处解析，避免事件回调里调用同步 API）"""
        try:
            if "/x/vu/web/add" in response.url:
                self._submit_api_responses.append(response)
                print(f"  📡 捕获投稿接口响应: {response.status} {response.url[:100]}")
        except Exception:
            pass

    def _inject_cookies(self, cookies_json_path):
        """从 JSON 文件注入 Cookie"""
        with open(cookies_json_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)

        playwright_cookies = []
        for c in cookies:
            cookie = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".bilibili.com"),
                "path": c.get("path", "/"),
                "secure": c.get("secure", True),
            }
            # sameSite
            same_site = c.get("sameSite", "Lax")
            if same_site in ("Strict", "Lax", "None"):
                cookie["sameSite"] = same_site
            else:
                cookie["sameSite"] = "Lax"
            # httpOnly 不通过 add_cookies 设置（Playwright 不支持）
            playwright_cookies.append(cookie)

        self.context.add_cookies(playwright_cookies)
        sessdata = any(c["name"] == "SESSDATA" for c in playwright_cookies)
        bili_jct = any(c["name"] == "bili_jct" for c in playwright_cookies)
        print(f"  🍪 已注入 {len(playwright_cookies)} 个 Cookie (SESSDATA={sessdata}, bili_jct={bili_jct})")

    def _navigate(self):
        """打开投稿页"""
        self.page.goto(self.UPLOAD_URL, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        print(f"  🌐 已打开投稿页: {self.page.url}")
        self._take_screenshot("01_navigate", full_page=True)

    def _check_login(self):
        """登录态检测：若跳转到登录页则失败"""
        url = self.page.url
        if "passport.bilibili.com/login" in url or "passport.bilibili.com/sso" in url:
            raise RuntimeError(f"登录态失效，页面被重定向到登录页: {url}")
        # 检查页面是否有登录表单
        login_form = self.page.query_selector("input[type='password']")
        if login_form:
            raise RuntimeError("登录态失效，页面出现登录表单")
        print("  ✅ 登录态正常")
        self._take_screenshot("02_login_check", full_page=True)

    def _close_notification(self):
        """关闭通知弹窗（若有）"""
        self._take_screenshot("03_before_close_notification")
        selectors = [
            'button:has-text("知道了")',
            'button:has-text("暂不设置")',
            '.close-btn',
            '[class*="close"]',
        ]
        for sel in selectors:
            try:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    el.click(timeout=2000)
                    print("  🔕 已关闭通知弹窗")
                    time.sleep(1)
                    self._take_screenshot("03_after_close_notification")
                    return
            except Exception:
                continue
        self._take_screenshot("03_after_close_notification_none")

    def _upload_video(self):
        """上传视频文件"""
        print("  📹 开始上传视频...")
        self._take_screenshot("04_before_upload_video", full_page=True)
        time.sleep(3)
        # B站投稿页的视频上传 input 是隐藏的 file input
        selectors = [
            'input[type="file"][accept*="video"]',
            'input[type="file"][accept*="mp4"]',
            'input[type="video"]',
            'input[type="file"]',
        ]
        file_input = None
        for sel in selectors:
            file_input = self.page.query_selector(sel)
            if file_input:
                break

        if not file_input:
            raise RuntimeError("未找到视频上传 input 元素")

        # 让 input 可见（B站用 display:none 隐藏，需先暴露再 SetInputFiles）
        file_input.evaluate("""el => {
            el.style.display = 'block';
            el.style.visibility = 'visible';
            el.style.opacity = '1';
            el.style.position = 'fixed';
            el.style.top = '0';
            el.style.left = '0';
            el.style.width = '200px';
            el.style.height = '50px';
            el.style.zIndex = '99999';
        }""")
        time.sleep(0.5)

        file_input.set_input_files(self.video_path)
        print("  📁 set_input_files 已调用")

        # 触发多种事件确保 B站 React 捕获（与参考项目一致）
        self.page.evaluate("""() => {
            const inputs = document.querySelectorAll('input[type="file"]');
            for (const input of inputs) {
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('input', { bubbles: true }));
                const reactPropsKey = Object.keys(input).find(k => k.startsWith('__reactProps$'));
                if (reactPropsKey && input[reactPropsKey] && input[reactPropsKey].onChange) {
                    input[reactPropsKey].onChange({
                        target: input,
                        currentTarget: input,
                        preventDefault: () => {},
                        stopPropagation: () => {},
                        nativeEvent: new Event('change'),
                        persist: () => {},
                        type: 'change'
                    });
                }
            }
        }""")
        print("  ⚡ 已触发 change/input/React onChange 事件")

        # 等待上传完成（检测标题输入框出现或 URL 跳转）
        print("  ⏳ 等待视频上传完成...")
        deadline = time.time() + 300  # 5 分钟
        while time.time() < deadline:
            url = self.page.url
            if "/platform/edit" in url or "/video/manage" in url:
                print("  ✅ 视频上传完成")
                self._take_screenshot("04_after_upload_video", full_page=True)
                return
            title_input = self.page.query_selector('input[placeholder*="标题"]')
            if title_input:
                print("  ✅ 视频上传完成（标题输入框已出现）")
                self._take_screenshot("04_after_upload_video", full_page=True)
                return
            # 检查错误信息
            error_text = self.page.query_selector('[class*="error"]:has-text("上传失败")')
            if error_text:
                raise RuntimeError("视频上传失败，页面显示错误信息")
            time.sleep(10)

        raise RuntimeError("视频上传超时（5 分钟）")

    def _get_upload_state(self):
        """读取当前视频上传状态（进度百分比 / 完成 / 失败）"""
        raw = self.page.evaluate(r"""() => {
            const text = (document.body && document.body.innerText) || '';
            const progressEls = document.querySelectorAll(
                '[class*="progress"], [class*="upload"], [class*="percent"]'
            );
            const percents = [];
            for (const el of progressEls) {
                const t = (el.innerText || el.textContent || '').trim();
                const m = t.match(/(\d{1,3})\s*%/g);
                if (m) m.forEach(s => percents.push(parseInt(s)));
                const w = (el.style && el.style.width) || '';
                if (w.trim().endsWith('%')) percents.push(parseInt(w));
                const now = el.getAttribute('aria-valuenow');
                if (now) percents.push(parseInt(now));
            }
            const bodyMatch = text.match(/(\d{1,3})\s*%/g) || [];
            const bodyPercents = bodyMatch.map(s => parseInt(s));
            // 注意：上传页常驻提示“信息填完后，就可投稿！不需等待上传完成哦～”也包含“上传完成”，
            // 必须先剔除这类提示，否则会立刻误判为上传完成（Run #14 就是这样）。
            const sanitized = text
                .replace(/不需等待上传完成[^\n]*/g, '')
                .replace(/无需等待上传完成[^\n]*/g, '');
            const waitingSubmit = /等待视频上传完成/.test(text);
            return JSON.stringify({
                hasFail: /上传失败|上传出错|上传中断/.test(sanitized),
                hasDone: /上传完成|上传成功/.test(sanitized) && !waitingSubmit,
                waitingSubmit: waitingSubmit,
                hasUploading: /上传中|正在上传|MB\/s|MB\/S/.test(text),
                maxProgressPercent: percents.length ? Math.max(...percents) : null,
                maxBodyPercent: bodyPercents.length ? Math.max(...bodyPercents) : null,
                snippet: text.replace(/\s+/g, ' ').slice(0, 300)
            });
        }""")
        import json as _json
        return _json.loads(raw) if raw else {}

    def _wait_for_upload_complete(self, timeout=None, stall_timeout=None):
        """等待视频文件真正上传完成（监控进度，卡死/超时报错）

        轮询页面上的上传进度，满足任一条件即视为完成：
        - 页面显示“上传完成/上传成功”
        - 进度百分比达到 100%

        连续 stall_timeout 秒进度不变化视为卡死（B站在网速骤降时会停在 9x%），
        直接抛错，避免像 Run #13 那样“假成功”。
        """
        timeout = timeout or self.UPLOAD_TIMEOUT
        stall_timeout = stall_timeout or self.UPLOAD_STALL_TIMEOUT
        if self._upload_confirmed:
            print("  ✅ 视频已确认上传完成，跳过等待")
            return
        print("  ⏳ 等待视频文件真正上传完成（进度监控）...")

        start = time.time()
        last_percent = None
        last_change = time.time()
        last_log = 0.0
        no_progress_checks = 0

        while time.time() - start < timeout:
            state = self._get_upload_state()
            elapsed = int(time.time() - start)

            if state.get("hasFail"):
                self._take_screenshot("04_upload_failed", full_page=True)
                raise RuntimeError(f"视频上传失败：{state.get('snippet', '')[:200]}")

            percent = state.get("maxProgressPercent")
            if percent is None:
                percent = state.get("maxBodyPercent")

            # “上传完成”文案只有在没有进度或进度已到 100% 时才可信，
            # 避免页面上其他提示文案干扰（进度 87% 时不可能已完成）。
            if state.get("hasDone") and (percent is None or percent >= 100):
                print(f"  ✅ 视频上传完成（页面提示，耗时 {elapsed}s）")
                time.sleep(3)
                self._take_screenshot("04_after_upload_complete", full_page=True)
                return

            if percent is not None:
                no_progress_checks = 0
                if last_percent is None or percent != last_percent:
                    last_percent = percent
                    last_change = time.time()
                if percent >= 100:
                    print(f"  ✅ 视频上传完成（进度 100%，耗时 {elapsed}s）")
                    time.sleep(3)
                    self._take_screenshot("04_after_upload_complete", full_page=True)
                    return
                if time.time() - last_change > stall_timeout:
                    self._take_screenshot("04_upload_stalled", full_page=True)
                    raise RuntimeError(
                        f"视频上传卡死：{stall_timeout}s 无进度（停留在 {percent}%），"
                        f"页面：{state.get('snippet', '')[:200]}"
                    )
                if time.time() - last_log > 30:
                    print(f"  ⏳ 上传中 {percent}%（已等待 {elapsed}s）")
                    last_log = time.time()
            else:
                # 页面暂时没有进度信息：只有在等待足够久、且连续多次都没有“上传中”字样时，
                # 才按上传完成处理（避免上传刚开始、进度条还没渲染就误判）
                no_progress_checks += 1
                if elapsed > 120 and not state.get("hasUploading") and no_progress_checks >= 6:
                    print(f"  ⚠️ 页面未显示进度，但已无上传中标识，按上传完成处理（{elapsed}s）")
                    self._take_screenshot("04_after_upload_assumed", full_page=True)
                    return
                if time.time() - last_log > 30:
                    print(f"  ⏳ 等待上传进度...（已等待 {elapsed}s）")
                    last_log = time.time()

            time.sleep(5)

        self._take_screenshot("04_upload_timeout", full_page=True)
        raise RuntimeError(f"视频上传超时（{timeout}s 未完成）")

    def _handle_confirm_dialog(self):
        """处理提示弹窗（JS 检测 .bcc-dialog，优先关闭类按钮，用原生鼠标点击）"""
        try:
            info = self.page.evaluate("""() => {
                var dialogs = document.querySelectorAll('.bcc-dialog, [class*="dialog-body"], [class*="modal-body"]');
                var dialog = null;
                for (var d of dialogs) {
                    if (d.offsetParent !== null) { dialog = d; break; }
                }
                if (!dialog) {
                    var wraps = document.querySelectorAll('.bcc-dialog__wrap, [class*="dialog-wrap"]');
                    for (var w of wraps) {
                        if (w.offsetParent !== null || getComputedStyle(w).display !== 'none') { dialog = w; break; }
                    }
                }
                if (!dialog) return JSON.stringify({status: 'NO_DIALOG'});
                var dialogText = dialog.textContent.trim().substring(0, 200);
                var btns = dialog.querySelectorAll('button, .bcc-button, [class*="btn"], span[class*="submit"], a');
                var visibleBtns = [];
                for (var b of btns) {
                    if (b.offsetParent !== null && b.offsetWidth > 0 && b.offsetHeight > 0) {
                        visibleBtns.push(b);
                    }
                }
                // 第1优先级：关闭类按钮
                var closeKeywords = ['暂不设置', '稍后再说', '以后再说', '我知道了', '知道了', '关闭', '取消', '跳过', '暂不', '不用了'];
                var targetBtn = null;
                for (var b of visibleBtns) {
                    var t = (b.textContent || '').trim();
                    for (var kw of closeKeywords) {
                        if (t.indexOf(kw) !== -1) { targetBtn = b; break; }
                    }
                    if (targetBtn) break;
                }
                // 第2优先级：确认类按钮
                if (!targetBtn) {
                    var confirmKeywords = ['确认', '确定', '是', '投稿', '同意', '继续', '好的', '完成', '去试试', '立即体验'];
                    for (var b of visibleBtns) {
                        var t = (b.textContent || '').trim();
                        for (var kw of confirmKeywords) {
                            if (t.indexOf(kw) !== -1) { targetBtn = b; break; }
                        }
                        if (targetBtn) break;
                    }
                }
                // 第3优先级：只有一个可见按钮就用它
                if (!targetBtn && visibleBtns.length === 1) { targetBtn = visibleBtns[0]; }
                // 第4优先级：多个按钮取最后一个
                if (!targetBtn && visibleBtns.length > 0) { targetBtn = visibleBtns[visibleBtns.length - 1]; }
                if (!targetBtn) return JSON.stringify({status: 'NO_DIALOG', reason: 'no_visible_btns'});
                targetBtn.scrollIntoView({block: 'center'});
                var rect = targetBtn.getBoundingClientRect();
                return JSON.stringify({
                    status: 'FOUND',
                    text: targetBtn.textContent.trim().substring(0, 30),
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    dialogText: dialogText
                });
            }""")
            if not info or "NO_DIALOG" in info:
                return

            import json as _json
            btn = _json.loads(info)
            print(f"  💬 检测到弹窗: {btn.get('dialogText', '')[:60]} | 按钮: {btn.get('text', '')}")

            # 用原生鼠标点击（JS click 不能触发 React onClick）
            self.page.mouse.move(btn["x"], btn["y"])
            time.sleep(0.2)
            self.page.mouse.click(btn["x"], btn["y"])
            print("  ✅ 弹窗按钮已点击")
            time.sleep(1)
        except Exception:
            pass

    def _upload_cover(self):
        """上传封面图片（对齐参考项目 4 步流程）

        步骤1：点击"添加封面"按钮
        步骤2：在弹窗内上传封面文件
        步骤3：勾选"双比例同步改动"复选框
        步骤4：点击"完成"按钮
        """
        if not self.cover_path or not os.path.exists(self.cover_path):
            print("  ⚠️ 无封面文件，跳过封面上传")
            return

        print("  🖼️ 开始上传封面...")
        self._take_screenshot("05_before_upload_cover", full_page=True)

        # ========== 步骤1：点击"添加封面"按钮 ==========
        res = self.page.evaluate("""() => {
            var spans = document.querySelectorAll('span.add-text');
            var btn = null;
            for (var el of spans) {
                var t = (el.textContent || '').trim();
                if (t === '添加封面' && el.offsetParent !== null && el.offsetWidth > 0) {
                    btn = el;
                    break;
                }
            }
            if (!btn) {
                var all = document.querySelectorAll('span, div, button');
                for (var el of all) {
                    var t = (el.textContent || '').trim();
                    if ((t === '添加封面' || t === '添加主封面') && el.offsetParent !== null && el.offsetWidth > 0 && el.offsetWidth < 200) {
                        btn = el;
                        break;
                    }
                }
            }
            if (!btn) return JSON.stringify({status: 'NO_BTN'});
            btn.scrollIntoView({block: 'center'});
            var rect = btn.getBoundingClientRect();
            return JSON.stringify({
                status: 'FOUND',
                text: btn.textContent.trim().substring(0, 20),
                x: rect.x + rect.width / 2,
                y: rect.y + rect.height / 2
            });
        }""")
        import json as _json
        if res:
            btn = _json.loads(res)
            if btn.get("status") == "FOUND":
                self.page.mouse.move(btn["x"], btn["y"])
                time.sleep(0.2)
                self.page.mouse.click(btn["x"], btn["y"])
                print(f"  ✅ 已点击添加封面按钮: {btn.get('text', '')}")
                time.sleep(3)
                self._take_screenshot("05_01_after_click_add")
            else:
                print("  ⚠️ 未找到添加封面按钮，跳过封面上传")
                return
        else:
            print("  ⚠️ 添加封面按钮无响应，跳过封面上传")
            return

        # ========== 步骤2：在弹窗内上传封面文件 ==========
        # 先等弹窗把视频帧/默认封面异步加载完并稳定，再上传。
        # Run #13 的失败原因：弹窗打开后默认封面仍在下方的异步加载中（05_01 为空、05_02 才出现视频帧），
        # 此时 set_input_files 设置的文件没有进入上传器，最后“完成”应用的是 B站默认视频帧封面。
        # 现在改为：等弹窗稳定 -> 点击“上传封面/拖拽图片或点击上传”走文件选择器 -> 校验文件真的进了 input。
        self._wait_cover_modal_ready()
        if not self._set_cover_file():
            self._take_screenshot("05_02_upload_failed", full_page=True)
            raise RuntimeError(
                "封面文件未能加入 B 站封面上传器，已中止投稿（避免发布无封面/默认封面视频）"
            )
        print("  📂 封面文件已设置，等待上传处理...")
        time.sleep(3)
        self._take_screenshot("05_02_after_upload")

        # ========== 步骤3：勾选"双比例同步改动"复选框 ==========
        sync_info = self.page.evaluate("""() => {
            var labels = document.querySelectorAll('label.sync-checkbox, .sync-checkbox-wrapper label, label.bcc-checkbox');
            var targetLabel = null;
            for (var lab of labels) {
                if (lab.offsetParent !== null && lab.offsetWidth > 0) {
                    // 检查是否在弹窗内
                    var p = lab.parentElement;
                    var inModal = false;
                    for (var i = 0; i < 12 && p; i++) {
                        var c = (p.className || '').toString();
                        if (c.indexOf('modal') !== -1 || c.indexOf('dialog') !== -1 || c.indexOf('pop') !== -1) {
                            inModal = true;
                            break;
                        }
                        p = p.parentElement;
                    }
                    if (inModal) { targetLabel = lab; break; }
                    if (!targetLabel) targetLabel = lab;
                    break;
                }
            }
            if (!targetLabel) return JSON.stringify({status: 'NO_LABEL'});
            var cls = targetLabel.className || '';
            var checked = cls.indexOf('bcc-checkbox-checked') !== -1;
            var icon = targetLabel.querySelector('.bcc-icon-ic_MenuButton-tick, .bcc-iconfont');
            var hasIcon = icon !== null;
            targetLabel.scrollIntoView({block: 'center'});
            var rect = targetLabel.getBoundingClientRect();
            return JSON.stringify({
                status: 'FOUND', checked: checked, hasIcon: hasIcon,
                className: cls,
                x: rect.x + rect.width / 2, y: rect.y + rect.height / 2
            });
        }""")
        if sync_info:
            sync_res = _json.loads(sync_info)
            print(f"  📋 双比例同步复选框: checked={sync_res.get('checked')} class={sync_res.get('className','')}")
            if sync_res.get("status") == "FOUND":
                if not sync_res.get("checked"):
                    print("  ☑️ 勾选双比例同步改动...")
                    self.page.mouse.move(sync_res["x"], sync_res["y"])
                    time.sleep(0.2)
                    self.page.mouse.click(sync_res["x"], sync_res["y"])
                    time.sleep(1)
                    # 验证是否勾选成功
                    check_res = self.page.evaluate("""() => {
                        var lab = document.querySelector('label.sync-checkbox, label.bcc-checkbox');
                        if (!lab) return 'NO_LABEL';
                        return lab.className.indexOf('bcc-checkbox-checked') !== -1 ? 'CHECKED' : 'UNCHECKED';
                    }""")
                    print(f"  📋 勾选后状态: {check_res}")
                else:
                    print("  📋 双比例同步已勾选，跳过")
            else:
                print("  ⚠️ 未找到双比例同步复选框")
        else:
            print("  ⚠️ 双比例同步复选框无响应")

        self._take_screenshot("05_03_after_sync_check")

        # ========== 步骤4：点击"完成"按钮 ==========
        complete_info = self.page.evaluate("""() => {
            var btns = document.querySelectorAll('button, .bcc-button, [class*="btn"], div[class*="button"], span[class*="submit"]');
            var completeBtn = null;
            for (var b of btns) {
                var t = (b.textContent || '').trim();
                if (t === '完成' && b.offsetParent !== null && b.offsetWidth > 0) {
                    // 优先在弹窗内找
                    var p = b.parentElement;
                    var inModal = false;
                    for (var i = 0; i < 12 && p; i++) {
                        var c = (p.className || '').toString();
                        if (c.indexOf('modal') !== -1 || c.indexOf('dialog') !== -1 || c.indexOf('pop') !== -1) {
                            inModal = true;
                            break;
                        }
                        p = p.parentElement;
                    }
                    if (inModal) { completeBtn = b; break; }
                    if (!completeBtn) completeBtn = b;
                    break;
                }
            }
            // 兜底：找包含"完成"的按钮
            if (!completeBtn) {
                for (var b of btns) {
                    var t = (b.textContent || '').trim();
                    if (t.indexOf('完成') !== -1 && b.offsetParent !== null && b.offsetWidth > 0) {
                        completeBtn = b;
                        break;
                    }
                }
            }
            if (!completeBtn) return JSON.stringify({status: 'NO_BTN'});
            completeBtn.scrollIntoView({block: 'center'});
            var rect = completeBtn.getBoundingClientRect();
            return JSON.stringify({
                status: 'FOUND', text: completeBtn.textContent.trim().substring(0, 10),
                className: completeBtn.className || '',
                x: rect.x + rect.width / 2, y: rect.y + rect.height / 2
            });
        }""")
        if complete_info:
            complete_res = _json.loads(complete_info)
            if complete_res.get("status") == "FOUND":
                print(f"  ✅ 点击完成按钮: {complete_res.get('text', '')}")
                self.page.mouse.move(complete_res["x"], complete_res["y"])
                time.sleep(0.2)
                self.page.mouse.click(complete_res["x"], complete_res["y"])
                time.sleep(3)
                self._take_screenshot("05_04_after_complete")
                print("  ✅ 封面已上传")
                if self._wait_cover_modal_closed():
                    print("  ✅ 封面弹窗已关闭（完成已生效）")
                else:
                    print("  ⚠️ 封面弹窗未关闭，可能仍有校验提示")
                if self._cover_present(wait=10):
                    print("  ✅ 表单已显示封面缩略图")
                    score = self._form_cover_similarity()
                    if score is not None and score > 55:
                        print(f"  ⚠️ 表单封面与本地封面差异较大（{score:.1f}），可能应用了默认封面")
                else:
                    print("  ⚠️ 表单中暂未检测到封面缩略图")
            else:
                print("  ⚠️ 未找到完成按钮，按ESC关闭")
                self.page.keyboard.press("Escape")
                time.sleep(1)
        else:
            print("  ⚠️ 完成按钮无响应，按ESC关闭")
            self.page.keyboard.press("Escape")
            time.sleep(1)

    def _cover_modal_state(self):
        """读取“封面制作”弹窗状态：图片数量、预览图数量、本地(blob/data)预览数、缩略图数"""
        import json as _json
        raw = self.page.evaluate("""() => {
            var dialogs = document.querySelectorAll('.bcc-dialog, [class*="dialog"], [class*="modal"]');
            var modal = null;
            for (var d of dialogs) {
                if (d.offsetParent !== null && (d.textContent || '').indexOf('封面制作') !== -1) { modal = d; break; }
            }
            if (!modal) return JSON.stringify({modal: false});
            var imgs = Array.from(modal.querySelectorAll('img'));
            var previews = 0, locals = 0, thumbs = 0;
            for (var img of imgs) {
                var r = img.getBoundingClientRect();
                if (!r.width || !r.height) continue;
                var src = img.src || '';
                if (/^blob:|^data:image/.test(src)) locals++;
                if (r.width >= 200 && r.height >= 120) previews++;
                if (r.width <= 120 && r.height <= 80) thumbs++;
            }
            return JSON.stringify({modal: true, images: imgs.length, previews: previews, locals: locals, thumbs: thumbs});
        }""")
        return _json.loads(raw) if raw else {"modal": False}

    def _wait_cover_modal_ready(self, timeout=12):
        """等封面弹窗把视频帧/默认封面加载完并稳定，避免上传时机撞上异步重渲染"""
        time.sleep(5)  # 给视频帧/默认封面异步加载留出时间
        deadline = time.time() + timeout
        last_key = None
        stable = 0
        while time.time() < deadline:
            state = self._cover_modal_state()
            if not state.get("modal"):
                time.sleep(0.5)
                continue
            key = (state.get("images", 0), state.get("thumbs", 0), state.get("previews", 0))
            if key == last_key:
                stable += 1
                if stable >= 2 and state.get("images", 0) > 0:
                    break
            else:
                stable = 0
                last_key = key
            time.sleep(1)
        time.sleep(1)
        print(f"  🖼️ 封面弹窗状态: {self._cover_modal_state()}")

    def _file_input_has_cover(self):
        """检查页面 file input 是否真的持有了我们的封面文件"""
        import json as _json
        try:
            name = os.path.basename(self.cover_path)
            raw = self.page.evaluate("""(name) => {
                const inputs = document.querySelectorAll('input[type="file"]');
                for (const inp of inputs) {
                    if (inp.files && inp.files.length > 0) {
                        for (const f of inp.files) {
                            if (f.name === name) return JSON.stringify({ok: true, name: f.name});
                        }
                    }
                }
                return JSON.stringify({ok: false, count: inputs.length});
            }""", name)
            info = _json.loads(raw) if raw else {"ok": False}
            if info.get("ok"):
                print(f"  ✅ file input 已持有封面文件: {info.get('name')}")
            return bool(info.get("ok"))
        except Exception:
            return False

    def _modal_has_local_preview(self):
        """弹窗内是否出现本地文件预览（blob:/data:），可作为上传生效的佐证"""
        return bool(self._cover_modal_state().get("locals"))

    def _set_cover_file(self):
        """把本地封面放进 B站封面上传器（文件选择器优先 + input 兜底 + 校验）"""
        import json as _json

        # 策略1：点击弹窗底部“上传封面/拖拽图片或点击上传”，走系统文件选择器
        try:
            raw = self.page.evaluate("""() => {
                var dialogs = document.querySelectorAll('.bcc-dialog, [class*="dialog"], [class*="modal"]');
                var modal = null;
                for (var d of dialogs) {
                    if (d.offsetParent !== null && (d.textContent || '').indexOf('封面制作') !== -1) { modal = d; break; }
                }
                var scope = modal || document;
                var all = scope.querySelectorAll('span, div, p, button, label');
                var best = null;
                for (var el of all) {
                    var t = (el.textContent || '').trim();
                    if (t === '拖拽图片或点击上传' && el.offsetParent !== null && el.offsetWidth > 0) { best = el; break; }
                }
                if (!best) {
                    for (var el of all) {
                        var t = (el.textContent || '').trim();
                        if (t.indexOf('上传封面') !== -1 && t.length < 12 && el.offsetParent !== null && el.offsetWidth < 220) { best = el; break; }
                    }
                }
                if (!best) return JSON.stringify({status: 'NOT_FOUND'});
                best.scrollIntoView({block: 'center'});
                var r = best.getBoundingClientRect();
                return JSON.stringify({
                    status: 'FOUND',
                    text: best.textContent.trim().substring(0, 20),
                    x: r.x + r.width / 2,
                    y: r.y + r.height / 2
                });
            }""")
            pos = _json.loads(raw) if raw else {"status": "NOT_FOUND"}
            print(f"  📍 封面上传区域: {pos}")
            if pos.get("status") == "FOUND":
                with self.page.expect_file_chooser(timeout=8000) as fc_info:
                    self.page.mouse.move(pos["x"], pos["y"])
                    time.sleep(0.2)
                    self.page.mouse.click(pos["x"], pos["y"])
                fc_info.value.set_files(self.cover_path)
                print("  📂 已通过文件选择器设置封面文件")
                time.sleep(1.5)
                if self._file_input_has_cover() or self._modal_has_local_preview():
                    return True
                print("  ⚠️ 文件选择器设置后未检测到封面文件，尝试直接设置 file input")
        except Exception as e:
            print(f"  ⚠️ 文件选择器上传失败: {e}")

        # 策略2：定位“拖拽图片或点击上传”所在容器内的 image input（精确对应封面上传器）
        try:
            raw = self.page.evaluate("""() => {
                var allInputs = Array.from(document.querySelectorAll('input[type="file"]'));
                var imageInputs = allInputs.filter(el => {
                    var acc = (el.accept || '').toLowerCase();
                    return acc.indexOf('image') !== -1 || acc.indexOf('png') !== -1 || acc.indexOf('jpg') !== -1;
                });
                var anchor = null;
                for (var el of document.querySelectorAll('span, div, p')) {
                    if ((el.textContent || '').trim() === '拖拽图片或点击上传' && el.offsetParent !== null) { anchor = el; break; }
                }
                if (!anchor) {
                    for (var el of document.querySelectorAll('span, div, p, button')) {
                        var t = (el.textContent || '').trim();
                        if (t.indexOf('上传封面') !== -1 && t.length < 12 && el.offsetParent !== null && el.offsetWidth < 220) { anchor = el; break; }
                    }
                }
                if (!anchor) return JSON.stringify({status: 'NO_ANCHOR'});
                var p = anchor;
                for (var depth = 0; depth < 8 && p; depth++) {
                    for (var idx = 0; idx < imageInputs.length; idx++) {
                        if (p.contains(imageInputs[idx])) {
                            return JSON.stringify({status: 'FOUND', index: allInputs.indexOf(imageInputs[idx]), imageIndex: idx});
                        }
                    }
                    p = p.parentElement;
                }
                return JSON.stringify({status: 'NO_INPUT_IN_CONTAINER'});
            }""")
            located = _json.loads(raw) if raw else {"status": "NO_ANCHOR"}
            print(f"  📍 封面上传器 input: {located}")
            if located.get("status") == "FOUND":
                handles = self.page.query_selector_all('input[type="file"]')
                target = handles[located["index"]] if located["index"] < len(handles) else None
                if target:
                    target.evaluate("el => { el.style.display='block'; el.style.visibility='visible'; el.style.opacity='1'; }")
                    target.set_input_files(self.cover_path)
                    time.sleep(1.0)
                    if self._file_input_has_cover() or self._modal_has_local_preview():
                        print("  📂 封面文件已设置（封面上传器 input）")
                        return True
                    print("  ⚠️ 封面上传器 input 未能接受封面文件")
        except Exception as e:
            print(f"  ⚠️ 定位封面上传器 input 失败: {e}")

        # 策略3：逐个 image input 尝试（倒序：底部“上传封面”的 input 通常最后渲染）
        try:
            handles = self.page.query_selector_all('input[type="file"]')
            candidates = []
            for h in handles:
                accept = (h.get_attribute("accept") or "").lower()
                if "image" in accept or "png" in accept or "jpg" in accept:
                    candidates.append(h)
            print(f"  📁 找到 {len(candidates)} 个 image file input（共 {len(handles)} 个 input）")
            for idx, h in enumerate(reversed(candidates)):
                number = len(candidates) - idx
                try:
                    h.evaluate("el => { el.style.display='block'; el.style.visibility='visible'; el.style.opacity='1'; }")
                    h.set_input_files(self.cover_path)
                    time.sleep(1.0)
                    if self._file_input_has_cover() or self._modal_has_local_preview():
                        print(f"  📂 封面文件已设置（image input #{number}）")
                        return True
                    print(f"  ⚠️ image input #{number} 未接受封面文件")
                except Exception as e:
                    print(f"  ⚠️ image input #{number} 设置失败: {e}")
        except Exception as e:
            print(f"  ⚠️ 遍历 image input 失败: {e}")

        return False

    def _form_cover_similarity(self):
        """对比表单封面缩略图与本地封面，返回平均像素差（越小越像），失败返回 None"""
        try:
            from PIL import Image, ImageChops, ImageStat

            best_handle = None
            for h in self.page.query_selector_all('[class*="cover"] img'):
                if not h.is_visible():
                    continue
                box = h.bounding_box()
                if not box:
                    continue
                if 100 <= box["width"] <= 420 and 50 <= box["height"] <= 320:
                    best_handle = h
                    break
            if not best_handle:
                return None
            thumb_path = os.path.join(self.work_dir, "cover_applied_thumb.png")
            best_handle.screenshot(path=thumb_path)
            with Image.open(self.cover_path) as a_img, Image.open(thumb_path) as b_img:
                a = a_img.convert("RGB").resize((48, 48), Image.LANCZOS)
                b = b_img.convert("RGB").resize((48, 48), Image.LANCZOS)
            diff = ImageChops.difference(a, b)
            score = sum(ImageStat.Stat(diff).mean) / 3.0
            print(f"  🔍 表单封面与本地封面差异: {score:.1f}（越小越接近）")
            return score
        except Exception as e:
            print(f"  ⚠️ 封面比对失败: {e}")
            return None

    def _wait_cover_modal_closed(self, timeout=15):
        """等待封面弹窗关闭（点击“完成”生效后的直接信号）"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self._cover_modal_state().get("modal"):
                return True
            time.sleep(1)
        return False

    def _cover_present(self, wait=0):
        """检测投稿表单中是否已显示封面缩略图

        以“以下为系统推荐封面”文字为锚点：封面缩略图位于该行之前，
        避免把系统推荐封面误判为已上传封面。wait>0 时轮询等待缩略图渲染。
        """
        import json as _json
        deadline = time.time() + (wait or 0)
        while True:
            try:
                raw = self.page.evaluate("""() => {
                    var anchor = null;
                    for (var el of document.querySelectorAll('div, span, p')) {
                        var t = (el.textContent || '').trim();
                        if (t.indexOf('以下为系统推荐封面') !== -1 && el.offsetParent !== null && el.offsetWidth > 0 && el.offsetWidth < 700) {
                            anchor = el;
                            break;
                        }
                    }
                    var hits = [];
                    for (var img of document.querySelectorAll('img')) {
                        var src = img.src || '';
                        if (!src || src.indexOf('data:image/svg') === 0) continue;
                        var r = img.getBoundingClientRect();
                        if (r.width < 80 || r.height < 40) continue;
                        if (r.width > 500 || r.height > 320) continue;
                        if (anchor) {
                            var cmp = anchor.compareDocumentPosition(img);
                            if (!(cmp & Node.DOCUMENT_POSITION_PRECEDING)) continue;
                        } else {
                            var p = img.parentElement, inCover = false;
                            for (var i = 0; i < 12 && p; i++) {
                                var c = ((p.className || '').toString()).toLowerCase();
                                if (c.indexOf('cover') !== -1) { inCover = true; break; }
                                p = p.parentElement;
                            }
                            if (!inCover) continue;
                        }
                        hits.push(src.slice(0, 100));
                    }
                    return JSON.stringify({count: hits.length, hits: hits.slice(0, 3)});
                }""")
                info = _json.loads(raw) if raw else {"count": 0}
                if info.get("count", 0) > 0:
                    print(f"  🖼️ 封面缩略图: {info.get('hits', [])[:1]}")
                    return True
            except Exception as e:
                print(f"  ⚠️ 封面检测失败: {e}")
            if time.time() >= deadline:
                return False
            time.sleep(2)

    def _fill_title(self):
        """填写标题"""
        print("  ✏️ 填写标题...")
        self._take_screenshot("06_before_fill_title", full_page=True)
        for attempt in range(5):
            try:
                title_input = self.page.query_selector('input[placeholder*="标题"]')
                if not title_input:
                    time.sleep(2)
                    continue
                title_input.fill(self.title)
                # 触发 React 事件
                self.page.evaluate("""() => {
                    const el = document.querySelector('input[placeholder*="标题"]');
                    if (el) {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }""")
                print(f"  ✅ 标题已填写: {self.title[:40]}")
                self._take_screenshot("06_after_fill_title", full_page=True)
                return
            except Exception as e:
                if attempt < 4:
                    time.sleep(2)
                    continue
                raise

    def _fill_tags(self):
        """填写标签（逐个输入后按 Enter）"""
        print(f"  🏷️ 填写标签（{len(self.tags)} 个）...")
        self._take_screenshot("09_before_fill_tags", full_page=True)
        for attempt in range(3):
            try:
                for tag in self.tags:
                    # 标签输入框 placeholder 通常含"回车键"或"创建标签"
                    tag_input = None
                    for sel in [
                        'input[placeholder*="回车键"]',
                        'input[placeholder*="标签"]',
                        'input[placeholder*="Enter"]',
                    ]:
                        tag_input = self.page.query_selector(sel)
                        if tag_input:
                            break
                    if not tag_input:
                        time.sleep(2)
                        tag_input = self.page.query_selector('input[placeholder*="标签"]')
                        if not tag_input:
                            return  # 没有标签输入框，跳过
                    tag_input.fill(tag)
                    tag_input.press("Enter")
                    time.sleep(0.5)
                print(f"  ✅ 标签已填写: {', '.join(self.tags)}")
                self._take_screenshot("09_after_fill_tags", full_page=True)
                return
            except Exception:
                if attempt < 2:
                    time.sleep(2)
                    continue
                # 兜底：JS 方式
                try:
                    self.page.evaluate(f"""() => {{
                        const inputs = document.querySelectorAll('input');
                        for (const input of inputs) {{
                            const ph = input.getAttribute('placeholder') || '';
                            if (ph.includes('标签') || ph.includes('回车键') || ph.includes('Enter')) {{
                                input.focus();
                            }}
                        }}
                    }}""")
                except Exception:
                    pass

    def _fill_description(self):
        """填写简介（Quill 富文本编辑器）

        参考项目对齐：优先 JS 直接赋值 innerText + 派发 input 事件（Quill 监听 input），
        keyboard.type 作为兜底。
        """
        print("  📝 填写简介...")
        self._take_screenshot("10_before_fill_description", full_page=True)
        for attempt in range(3):
            try:
                # 找 Quill 编辑器
                editor_info = self.page.evaluate("""() => {
                    var sel = '.ql-editor[contenteditable="true"]';
                    var el = document.querySelector(sel);
                    if (!el) {
                        sel = '.ql-editor';
                        el = document.querySelector(sel);
                    }
                    if (!el) return JSON.stringify({found: false});
                    el.scrollIntoView({block: 'center'});
                    el.focus();
                    // 清空已有内容
                    el.innerText = '';
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    return JSON.stringify({found: true, sel: sel});
                }""")
                import json as _json
                editor_found = _json.loads(editor_info)

                if editor_found.get("found"):
                    # JS 直接赋值 + input 事件（Quill 监听 input 事件来同步内容）
                    res = self.page.evaluate("""(desc) => {
                        var el = document.querySelector('.ql-editor[contenteditable="true"]');
                        if (!el) return 'NO_EDITOR';
                        el.focus();
                        el.innerText = desc;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        return 'OK:' + el.innerText.length;
                    }""", self.description)
                    print(f"  📋 简介 JS 赋值结果: {res}")

                    # 验证是否成功写入
                    verify = self.page.evaluate("""() => {
                        var el = document.querySelector('.ql-editor[contenteditable="true"]');
                        if (!el) return '';
                        return el.innerText;
                    }""")
                    if verify and self.description[:10] in verify:
                        print(f"  ✅ 简介已填写（{len(self.description)} 字）")
                        self._take_screenshot("10_after_fill_description", full_page=True)
                        return
                    # JS 赋值后验证未通过，尝试 keyboard.type 兜底
                    print("  ⚠️ JS 赋值验证未通过，尝试 keyboard.type 兜底...")
                    editor = self.page.query_selector('.ql-editor[contenteditable="true"]')
                    if editor:
                        editor.click()
                        self.page.keyboard.type(self.description, delay=15)
                        time.sleep(1)
                        print(f"  ✅ 简介已填写（keyboard.type，{len(self.description)} 字）")
                        self._take_screenshot("10_after_fill_description_kb", full_page=True)
                        return
                else:
                    # 兜底：找 textarea
                    textarea = self.page.query_selector('textarea')
                    if textarea:
                        textarea.fill(self.description)
                        print(f"  ✅ 简介已填写（textarea，{len(self.description)} 字）")
                        self._take_screenshot("10_after_fill_description_textarea", full_page=True)
                        return

                if attempt < 2:
                    time.sleep(2)
                    continue
                print("  ⚠️ 简介填写失败，继续")
            except Exception:
                if attempt < 2:
                    time.sleep(2)
                    continue
                print("  ⚠️ 简介填写失败，继续")

    def _select_ai_declaration(self):
        """选择创作声明：点击下拉框→选"含AI生成内容"（与参考项目一致）"""
        print("  🤖 选择 AI 声明...")
        self._take_screenshot("07_before_ai_declaration", full_page=True)
        # 滚动到创作声明区域
        self.page.evaluate("""() => {
            var els = document.evaluate('//*[contains(text(),"创作声明")]', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            var el = els.singleNodeValue;
            if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' });
        }""")
        time.sleep(1)

        # 点击下拉框
        res = self.page.evaluate("""() => {
            var input = document.querySelector('input.bcc-select-input-inner[placeholder*="创作声明"]')
                     || document.querySelector('input[placeholder*="创作声明"]');
            if (!input) return 'NO_INPUT';
            input.click();
            input.focus();
            return 'CLICKED';
        }""")
        print(f"  📋 AI声明下拉框: {res}")
        time.sleep(1)

        # 选择"含AI生成内容"
        res2 = self.page.evaluate("""() => {
            var spans = document.querySelectorAll('span');
            for (var i = 0; i < spans.length; i++) {
                if (spans[i].textContent && spans[i].textContent.indexOf('含AI生成内容') !== -1) {
                    spans[i].click();
                    return 'SELECTED';
                }
            }
            return 'NOT_FOUND';
        }""")
        print(f"  ✅ AI声明选择: {res2}")
        time.sleep(1)
        self._take_screenshot("07_after_ai_declaration", full_page=True)
        if res2 != "SELECTED":
            print("  ⚠️ 未找到 AI 声明选项，跳过")

    def _select_district(self):
        """选择分区：资讯（JS 点击 select-controller→选"资讯"，与参考项目一致）"""
        print("  📂 选择分区...")
        self._take_screenshot("08_before_district", full_page=True)
        # 滚动到分区区域
        self.page.evaluate("""() => {
            var els = document.evaluate('//*[contains(text(),"分区")]', document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            var el = els.singleNodeValue;
            if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' });
        }""")
        time.sleep(1)

        # 检查当前分区，如果不是"资讯"则点击切换
        res = self.page.evaluate("""() => {
            var ctrl = document.querySelector('div.select-controller');
            if (!ctrl) return 'NO_CONTROLLER';
            var cur = ctrl.querySelector('p.select-item-cont');
            if (cur && cur.textContent && cur.textContent.indexOf('资讯') !== -1) return 'ALREADY_NEWS';
            ctrl.click();
            return 'CLICKED';
        }""")
        print(f"  📂 分区控制器: {res}")
        if res == "ALREADY_NEWS":
            return
        time.sleep(1)

        # 选择"资讯"
        res2 = self.page.evaluate("""() => {
            var items = document.querySelectorAll('div[title="资讯"]');
            if (items.length > 0) {
                items[0].click();
                return 'SELECTED';
            }
            var ps = document.querySelectorAll('p');
            for (var i = 0; i < ps.length; i++) {
                if (ps[i].textContent === '资讯') {
                    ps[i].click();
                    return 'SELECTED_P';
                }
            }
            return 'NOT_FOUND';
        }""")
        print(f"  ✅ 分区选择: {res2}")
        time.sleep(1)
        self._take_screenshot("08_after_district", full_page=True)
        if res2 == "NOT_FOUND":
            print("  ⚠️ 未找到分区选择器，跳过")

    def _submit(self):
        """点击投稿按钮提交

        参考项目对齐：
        1. 投稿按钮用文本搜索兜底（不只是 CSS 选择器）
        2. 点击后等 5 秒 + 截图
        3. 确认弹窗重试 3 次（弹窗可能延迟出现）
        4. 再等 5 秒 + 截图
        5. 未检测到 URL 跳转不报错，仅记录日志后继续轮询 BV 号
        """
        print("  📤 提交投稿...")
        # 双保险：投稿前再次确认视频已上传到 100%（已确认过则立即返回）
        self._wait_for_upload_complete()
        self._take_screenshot("11_before_submit", full_page=True)
        # 先关闭可能存在的弹窗（调用两次，可能有多层弹窗）
        print("  🔍 检查并关闭已有弹窗...")
        self._handle_confirm_dialog()
        time.sleep(1)
        self._handle_confirm_dialog()
        time.sleep(1)

        # 找投稿按钮：精确文本匹配 + 滚动到视口中央
        # 关键：按钮在页面最底部（y 可能 > 视口高度），不滚动到视口内则 mouse.click 点不中
        btn_info_raw = self.page.evaluate("""() => {
            var candidates = document.querySelectorAll('button, .bcc-button, [class*="btn"], [class*="submit"], span, div, a');
            var best = null;
            // 1) 精确文本 "立即投稿"
            for (var el of candidates) {
                var t = (el.textContent || '').trim();
                if (t === '立即投稿' && el.offsetParent !== null && el.offsetWidth > 0 && el.offsetHeight > 0) {
                    best = el; break;
                }
            }
            // 2) 包含 "立即投稿"（短文本）
            if (!best) {
                for (var el of candidates) {
                    var t = (el.textContent || '').trim();
                    if (t.indexOf('立即投稿') !== -1 && t.length < 20 && el.offsetParent !== null && el.offsetWidth > 0) {
                        best = el; break;
                    }
                }
            }
            if (!best) return JSON.stringify({status: 'NOT_FOUND'});
            best.scrollIntoView({block: 'center', inline: 'center'});
            var rect = best.getBoundingClientRect();
            var disabled = best.disabled || best.classList.contains('disabled') || best.getAttribute('disabled') !== null;
            return JSON.stringify({
                status: 'FOUND',
                text: best.textContent.trim().substring(0, 20),
                tag: best.tagName,
                className: (best.className || '').toString().substring(0, 60),
                disabled: disabled,
                x: rect.x + rect.width / 2,
                y: rect.y + rect.height / 2,
                vh: window.innerHeight
            });
        }""")
        import json as _json
        submit_info = _json.loads(btn_info_raw) if btn_info_raw else {"status": "NOT_FOUND"}
        print(f"  📍 投稿按钮信息: {submit_info}")

        if submit_info.get("status") != "FOUND":
            raise RuntimeError("未找到投稿按钮")
        if submit_info.get("disabled"):
            form_errors = self._check_form_errors()
            raise RuntimeError(f"投稿按钮禁用: {form_errors or '表单可能未填完整'}")

        # 滚动后等待页面稳定
        time.sleep(1)

        # 优先用 Playwright element.click()（自动滚动 + 真实鼠标事件 + 可操作性检查）
        clicked = False
        try:
            submit_btn = self.page.query_selector('button:has-text("立即投稿")')
            if submit_btn:
                submit_btn.click(timeout=10000)
                clicked = True
                print("  🖱️ 投稿按钮已点击（element.click）")
        except Exception as e:
            print(f"  ⚠️ element.click 失败: {e}，改用坐标点击")

        if not clicked:
            # 坐标点击兜底：再次滚动到视口中央后重新取坐标
            idx = self.page.evaluate("""() => {
                var candidates = document.querySelectorAll('button, [class*="btn"], span, div, a');
                for (var el of candidates) {
                    var t = (el.textContent || '').trim();
                    if (t === '立即投稿' && el.offsetParent !== null && el.offsetWidth > 0) {
                        el.scrollIntoView({block: 'center', inline: 'center'});
                        var r = el.getBoundingClientRect();
                        return JSON.stringify({x: r.x + r.width/2, y: r.y + r.height/2, vh: window.innerHeight});
                    }
                }
                return JSON.stringify({status: 'NOT_FOUND'});
            }""")
            pos = _json.loads(idx)
            if pos.get("status") == "NOT_FOUND":
                raise RuntimeError("滚动后仍未找到投稿按钮")
            print(f"  📍 点击坐标: ({pos['x']:.0f}, {pos['y']:.0f})，视口高 {pos['vh']}")
            if pos["y"] > pos["vh"] or pos["y"] < 0:
                raise RuntimeError(f"投稿按钮仍在视口外（y={pos['y']:.0f}, vh={pos['vh']}）")
            self.page.mouse.move(pos["x"], pos["y"])
            time.sleep(0.3)
            self.page.mouse.click(pos["x"], pos["y"])
            print("  🖱️ 投稿按钮已点击（坐标点击）")

        # 等 5 秒让确认弹窗出现
        time.sleep(5)
        self._take_screenshot("11_after_submit_click", full_page=True)

        # 处理二次确认弹窗（重试 3 次，弹窗可能延迟出现）
        print("  🔍 处理确认弹窗...")
        self._retry_handle_dialog(3)

        # 再等 5 秒看是否跳转
        time.sleep(5)
        self._take_screenshot("11_after_confirm", full_page=True)

        # 等待投稿真正被受理：优先用投稿接口返回的 BV，其次看 URL 跳转
        deadline = time.time() + 300  # 5 分钟
        while time.time() < deadline:
            bvid = self._extract_bvid_from_submit_responses()
            if bvid:
                self.submit_bvid = bvid
                print(f"  ✅ 投稿已受理，BV 号: {bvid}")
                return

            url = self.page.url
            if "/video/manage" in url or "/platform/edit" in url:
                print(f"  ✅ 投稿已提交，跳转到: {url}")
                return

            # 检查是否有错误提示
            error_msg = self._check_submit_errors()
            if error_msg:
                self._take_screenshot("submit_error")
                raise RuntimeError(f"投稿提交失败: {error_msg}")

            time.sleep(5)
            snippet = self._get_body_text()[:300]
            if "等待视频上传完成" in snippet:
                print("  ⚠️ B站提示“等待视频上传完成后会自动提交”，继续等待...")

        # 无跳转也无错误，可能投稿在后台处理中，继续轮询 BV 号
        print(f"  ⚠️ 5 分钟内未拿到 BV/跳转（当前: {self.page.url}），继续轮询")
        self._take_screenshot("11_final_check", full_page=True)

    def _get_body_text(self):
        """读取页面正文文本（失败返回空串）"""
        try:
            return self.page.evaluate("() => (document.body && document.body.innerText) || ''") or ""
        except Exception:
            return ""

    def _find_bvid_in_obj(self, obj):
        """递归查找 JSON 中的 bvid 字段"""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if str(key).lower() == "bvid" and isinstance(value, str) and value.startswith("BV"):
                    return value
            for value in obj.values():
                found = self._find_bvid_in_obj(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = self._find_bvid_in_obj(value)
                if found:
                    return found
        return None

    def _extract_bvid_from_submit_responses(self):
        """从拦截到的投稿接口响应中提取 BV 号"""
        import re
        for resp in list(self._submit_api_responses):
            try:
                data = resp.json()
                bvid = self._find_bvid_in_obj(data)
                if bvid:
                    return bvid
            except Exception:
                pass
            try:
                text = resp.text()
                match = re.search(r"(BV[a-zA-Z0-9]{10})", text or "")
                if match:
                    return match.group(1)
            except Exception:
                pass
        return None

    def _find_recent_bvid_via_member_api(self, title_prefix):
        """在已登录的浏览器里调用创作中心接口，按标题匹配最新稿件

        比抓个人空间页面稳定：个人空间有风控，创作中心接口使用同一登录态。
        """
        try:
            raw = self.page.evaluate("""async (titlePrefix) => {
                const urls = [
                    'https://member.bilibili.com/x/web/archives?status=is_pubing,pubed,not_pubed&pn=1&ps=20&coined=0',
                    'https://member.bilibili.com/x/web/archives?status=all&pn=1&ps=20'
                ];
                for (const u of urls) {
                    try {
                        const r = await fetch(u, { credentials: 'include' });
                        const j = await r.json();
                        if (j && j.code === 0 && j.data && Array.isArray(j.data.arc_audits)) {
                            const items = j.data.arc_audits.map(x => x.Archive || x.archive || x);
                            for (const a of items) {
                                if (a.bvid && a.title && a.title.indexOf(titlePrefix) !== -1) {
                                    return JSON.stringify({ ok: true, bvid: a.bvid, title: a.title });
                                }
                            }
                            return JSON.stringify({ ok: true, bvid: null, count: items.length });
                        }
                    } catch (e) {}
                }
                return JSON.stringify({ ok: false });
            }""", title_prefix)
            import json as _json
            result = _json.loads(raw) if raw else {"ok": False}
            if result.get("bvid"):
                return result["bvid"]
            if result.get("ok"):
                print(f"  ⏳ 创作中心有 {result.get('count', 0)} 个稿件，暂无标题匹配「{title_prefix}」")
        except Exception as e:
            print(f"  ⚠️ 创作中心接口查询失败: {e}")
        return None

    def _retry_handle_dialog(self, max_retries):
        """重试处理确认弹窗（弹窗可能延迟出现）"""
        for attempt in range(max_retries):
            info = self.page.evaluate("""() => {
                var dialogs = document.querySelectorAll('.bcc-dialog, [class*="dialog-body"], [class*="modal-body"]');
                var dialog = null;
                for (var d of dialogs) {
                    if (d.offsetParent !== null) { dialog = d; break; }
                }
                if (!dialog) {
                    var wraps = document.querySelectorAll('.bcc-dialog__wrap, [class*="dialog-wrap"]');
                    for (var w of wraps) {
                        if (w.offsetParent !== null || getComputedStyle(w).display !== 'none') { dialog = w; break; }
                    }
                }
                if (!dialog) return JSON.stringify({status: 'NO_DIALOG'});
                var btns = dialog.querySelectorAll('button, .bcc-button, [class*="btn"], span[class*="submit"], a');
                var visibleBtns = [];
                for (var b of btns) {
                    if (b.offsetParent !== null && b.offsetWidth > 0 && b.offsetHeight > 0) {
                        visibleBtns.push(b);
                    }
                }
                var closeKeywords = ['暂不设置', '稍后再说', '以后再说', '我知道了', '知道了', '关闭', '取消', '跳过', '暂不', '不用了'];
                var confirmKeywords = ['确认', '确定', '是', '投稿', '同意', '继续', '好的', '完成', '去试试', '立即体验'];
                var targetBtn = null;
                for (var b of visibleBtns) {
                    var t = (b.textContent || '').trim();
                    for (var kw of closeKeywords) {
                        if (t.indexOf(kw) !== -1) { targetBtn = b; break; }
                    }
                    if (targetBtn) break;
                }
                if (!targetBtn) {
                    for (var b of visibleBtns) {
                        var t = (b.textContent || '').trim();
                        for (var kw of confirmKeywords) {
                            if (t.indexOf(kw) !== -1) { targetBtn = b; break; }
                        }
                        if (targetBtn) break;
                    }
                }
                if (!targetBtn && visibleBtns.length === 1) { targetBtn = visibleBtns[0]; }
                if (!targetBtn && visibleBtns.length > 0) { targetBtn = visibleBtns[visibleBtns.length - 1]; }
                if (!targetBtn) return JSON.stringify({status: 'NO_DIALOG', reason: 'no_visible_btns'});
                targetBtn.scrollIntoView({block: 'center'});
                var rect = targetBtn.getBoundingClientRect();
                return JSON.stringify({
                    status: 'FOUND',
                    text: targetBtn.textContent.trim().substring(0, 30),
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    dialogText: dialog.textContent.trim().substring(0, 200)
                });
            }""")
            import json as _json
            btn = _json.loads(info)
            if btn.get("status") != "FOUND":
                if attempt < max_retries - 1:
                    time.sleep(2)
                continue

            print(f"  💬 检测到弹窗: {btn.get('dialogText', '')[:60]} | 按钮: {btn.get('text', '')}")
            self.page.mouse.move(btn["x"], btn["y"])
            time.sleep(0.2)
            self.page.mouse.click(btn["x"], btn["y"])
            print("  ✅ 弹窗按钮已点击")
            time.sleep(2)
            return

    def _check_submit_errors(self):
        """检测提交后的页面错误提示（toast / 表单验证），返回错误信息或空字符串

        注意：只检测真正的错误元素，不匹配信息性提示（如"成为UP主的第X天"等）。
        通过错误类名 + 错误关键词文本双重判定，避免误报。
        """
        try:
            info = self.page.evaluate("""() => {
                var errors = [];
                // 1. 检测错误专用 toast/提示元素（类名明确包含 error）
                var errorSelectors = [
                    '[class*="toast-error"]',
                    '[class*="bcc-toast-error"]',
                    '.bcc-message-error',
                    '[class*="message-error"]',
                    '[class*="error-text"]',
                    '[class*="form-error"]',
                    '[class*="tips-error"]',
                    '[class*="tips--error"]',
                    '[class*="error-tips"]',
                    '.bcc-tips--error',
                ];
                for (var sel of errorSelectors) {
                    var els = document.querySelectorAll(sel);
                    for (var el of els) {
                        if (el.offsetParent !== null && el.offsetWidth > 0) {
                            var t = (el.textContent || '').trim();
                            if (t) errors.push(sel + ': ' + t.substring(0, 100));
                        }
                    }
                }
                // 2. 检测错误关键词文本（在所有可见元素中搜索错误关键词）
                // 错误关键词：失败、错误、请填写、不能为空、请选择、不符合、违规、不合法、未通过、已存在
                var errorKeywords = ['上传失败', '投稿失败', '提交失败', '操作失败', '请求失败',
                    '错误', '请填写', '不能为空', '请选择', '不符合', '违规', '不合法',
                    '未通过', '已存在', '格式错误', '校验失败'];
                // 只检查 toast/message 类容器内的文本，避免匹配到无关页面文本
                var messageContainers = document.querySelectorAll(
                    '[class*="toast"], [class*="message"], [class*="dialog"], [class*="alert"]'
                );
                for (var c of messageContainers) {
                    if (c.offsetParent === null || c.offsetWidth === 0) continue;
                    var t = (c.textContent || '').trim();
                    if (!t || t.length > 200) continue;
                    for (var kw of errorKeywords) {
                        if (t.indexOf(kw) !== -1) {
                            errors.push('msg: ' + t.substring(0, 100));
                            break;
                        }
                    }
                }
                return errors;
            }""")
            if info and len(info) > 0:
                return "; ".join(info[:3])
        except Exception:
            pass
        return ""

    def _check_form_errors(self):
        """检查表单是否有未填项或验证错误，返回错误描述列表"""
        try:
            errors = self.page.evaluate("""() => {
                var errors = [];
                // 检查必填字段是否有红框（只匹配错误专用类名，避免误匹配）
                var requiredSelectors = [
                    'input.bcc-input-inner--error',
                    '.bcc-tips--error',
                    '[class*="error-input"]',
                    '[class*="error-tips"]',
                ];
                for (var sel of requiredSelectors) {
                    var els = document.querySelectorAll(sel);
                    for (var el of els) {
                        if (el.offsetParent !== null) {
                            errors.push(sel + ' 字段有验证错误');
                        }
                    }
                }
                // 检查标题是否为空
                var titleInput = document.querySelector('input[placeholder*="标题"]');
                if (titleInput && (!titleInput.value || titleInput.value.trim() === '')) {
                    errors.push('标题未填写');
                }
                return errors;
            }""")
            return errors or []
        except Exception:
            return []

    def _wait_for_bvid(self):
        """获取 BV 号（投稿接口 → 创作中心接口 → 个人空间页面，逐级兜底）"""
        print("  🔍 获取 BV 号...")
        title_prefix = self.title[:8] if len(self.title) >= 8 else self.title

        # 1) 投稿接口返回值（最可靠）
        for attempt in range(6):
            if self.submit_bvid:
                print(f"  ✅ 从投稿接口获取 BV 号: {self.submit_bvid}")
                return self.submit_bvid
            bvid = self._extract_bvid_from_submit_responses()
            if bvid:
                print(f"  ✅ 从投稿接口获取 BV 号: {bvid}")
                return bvid
            try:
                url = self.page.url
                bvid = self._extract_bvid(url)
                if bvid:
                    print(f"  ✅ 从当前页面 URL 获取 BV 号: {bvid}")
                    return bvid
            except Exception:
                pass
            time.sleep(3)

        # 2) 创作中心接口 + 3) 个人空间页面轮询
        deadline = time.time() + 600  # 10 分钟
        attempt = 0
        while time.time() < deadline:
            attempt += 1

            bvid = self._find_recent_bvid_via_member_api(title_prefix)
            if bvid:
                print(f"  ✅ 已获取 BV 号: {bvid}（创作中心匹配）")
                return bvid

            # 每 3 轮才抓一次个人空间，减少风控
            if attempt % 3 == 1:
                try:
                    uid = self._get_uid()
                    if uid:
                        space_url = self.SPACE_URL_TEMPLATE.format(uid=uid)
                        space_page = self.context.new_page()
                        try:
                            space_page.goto(space_url, wait_until="domcontentloaded", timeout=60000)
                            time.sleep(3)
                            space_page.screenshot(
                                path=os.path.join(self.work_dir, "12_personal_space.png"),
                                full_page=False,
                            )
                            print("  📸 个人空间截图已保存")

                            # 查找标题匹配的视频链接（仅按标题前缀匹配，不匹配任意 /BV 链接）
                            links = space_page.query_selector_all("a[href*='/video/BV']")
                            for link in links:
                                href = link.get_attribute("href") or ""
                                link_text = (link.inner_text() or "").strip()
                                if title_prefix in link_text:
                                    bvid = self._extract_bvid(href)
                                    if bvid:
                                        print(f"  ✅ 已获取 BV 号: {bvid}（标题匹配）")
                                        return bvid
                            if links:
                                print(f"  ⏳ 个人空间有 {len(links)} 个视频，暂无标题匹配「{title_prefix}」，继续轮询...")
                        finally:
                            space_page.close()
                except Exception:
                    pass

            time.sleep(30)

        print("  ⚠️ 超时未获取到 BV 号（视频可能仍在审核中）")
        return None

    def _get_uid(self):
        """从 Cookie 中获取用户 UID"""
        cookies = self.context.cookies()
        for c in cookies:
            if c["name"] == "DedeUserID":
                return c["value"]
        return None

    @staticmethod
    def _extract_bvid(href):
        """从 URL 中提取 BV 号"""
        import re
        match = re.search(r"(BV[a-zA-Z0-9]+)", href)
        if match:
            return match.group(1)
        return None

    def _close(self):
        """关闭浏览器"""
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            print("  🔚 浏览器已关闭")
        except Exception:
            pass


# ── 回调 ────────────────────────────────────────────────────────────────


def send_callback(callback_url, secret, task_id, status, bvid=None, url=None, error=None):
    """发送上传结果回调（HMAC-SHA256 签名）"""
    import requests

    body_dict = {"task_id": task_id, "status": status}
    if bvid:
        body_dict["bvid"] = bvid
    if url:
        body_dict["url"] = url
    if error:
        body_dict["error"] = error

    body = json.dumps(body_dict, ensure_ascii=False)
    signature = base64.b64encode(
        hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    ).decode()

    resp = requests.post(
        callback_url,
        headers={
            "Content-Type": "application/json",
            "X-Callback-Signature": signature,
        },
        data=body,
        timeout=30,
    )
    print(f"  📨 回调已发送: {resp.status_code} {resp.text[:100]}")
    return resp.status_code < 400


# ── 主入口 ──────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="B站无头上传脚本")
    parser.add_argument("--task-id", required=True, help="任务 ID")
    parser.add_argument("--video-key", required=True, help="视频 R2 key")
    parser.add_argument("--cover-key", default="", help="封面 R2 key（可选）")
    parser.add_argument("--cookies-key", required=True, help="Cookie R2 key")
    parser.add_argument("--title", required=True, help="视频标题")
    parser.add_argument("--article-content", default="", help="文章内容（用于提炼简介/标签）")
    parser.add_argument("--orientation", default="landscape", help="方向")
    parser.add_argument("--callback-url", required=True, help="回调 URL")
    parser.add_argument("--callback-secret", required=True, help="回调 HMAC 密钥")
    parser.add_argument("--r2-bucket", required=True, help="R2 桶名")
    parser.add_argument("--r2-access-key-id", required=True, help="R2 Access Key ID")
    parser.add_argument("--r2-secret-access-key", required=True, help="R2 Secret Access Key")
    parser.add_argument("--r2-endpoint", required=True, help="R2 Endpoint URL")
    parser.add_argument("--agnes-api-key", default="", help="Agnes API Key")
    parser.add_argument("--agnes-base-url", default="https://apihub.agnes-ai.com/v1", help="Agnes Base URL")
    parser.add_argument("--work-dir", default="./bilibili_work", help="工作目录")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    task_id = args.task_id
    try:
        # 1. 下载视频、封面、Cookie
        video_path = work_dir / f"{task_id}_video.mp4"
        download_from_r2(
            args.video_key, str(video_path),
            args.r2_bucket, args.r2_access_key_id, args.r2_secret_access_key, args.r2_endpoint,
        )

        cover_path = None
        if args.cover_key:
            cover_path = work_dir / f"{task_id}_cover.jpg"
            download_from_r2(
                args.cover_key, str(cover_path),
                args.r2_bucket, args.r2_access_key_id, args.r2_secret_access_key, args.r2_endpoint,
            )

        cookies_path = work_dir / f"{task_id}_cookies.json"
        download_from_r2(
            args.cookies_key, str(cookies_path),
            args.r2_bucket, args.r2_access_key_id, args.r2_secret_access_key, args.r2_endpoint,
        )

        # 2. 用 Agnes 提炼简介和标签
        print("\n📝 正在用 Agnes 提炼简介和标签...")
        description, tags = extract_metadata(
            args.title, args.article_content, args.agnes_api_key, args.agnes_base_url,
        )

        # 3. 执行浏览器自动化上传
        print("\n🚀 开始 B站上传...")
        uploader = BilibiliUploader(
            video_path=str(video_path),
            cover_path=str(cover_path) if cover_path else None,
            cookies_path=str(cookies_path),
            title=args.title,
            description=description,
            tags=tags,
            work_dir=str(work_dir),
        )
        bvid, url = uploader.run()

        if bvid:
            print(f"\n✅ B站上传成功！BV: {bvid}")
            send_callback(args.callback_url, args.callback_secret, task_id, "success", bvid=bvid, url=url)
            sys.exit(0)
        else:
            print("\n⚠️ 视频已提交但未获取到 BV 号（可能在审核中）")
            send_callback(args.callback_url, args.callback_secret, task_id, "success", url=None)
            sys.exit(0)

    except Exception as e:
        error_msg = str(e)
        print(f"\n❌ B站上传失败: {error_msg}")
        send_callback(args.callback_url, args.callback_secret, task_id, "failed", error=error_msg)
        sys.exit(1)


if __name__ == "__main__":
    main()
