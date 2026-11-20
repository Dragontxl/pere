"""B站（哔哩哔哩）无头上传脚本

使用 Playwright 浏览器自动化完成 B站投稿页上传，参考 one_minute_recap
项目的 go-rod 实现，改用 Python + Playwright。

完整流程：
1. 从 R2 下载视频、封面、Cookie
2. 用 Agnes 从文章内容提炼简介和标签（不超过5个）
3. 启动无头浏览器，注入 Cookie，打开投稿页
4. 上传视频 → 上传封面 → 填标题/简介/标签 → 选 AI 声明/分区
5. 提交投稿，轮询个人空间获取 BV 号
6. 发送结果回调到后端

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

    def __init__(self, video_path, cover_path, cookies_path, title, description, tags, headless=True):
        self.video_path = video_path
        self.cover_path = cover_path
        self.cookies_path = cookies_path
        self.title = title
        self.description = description
        self.tags = tags
        self.headless = headless
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    def run(self):
        """执行上传，返回 (bvid, url) 或 (None, None)"""
        self._launch()
        try:
            self._inject_cookies(self.cookies_path)
            self._navigate()
            self._check_login()
            self._close_notification()
            self._upload_video()
            self._handle_confirm_dialog()
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
        print("  🚀 浏览器已启动")

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

    def _close_notification(self):
        """关闭通知弹窗（若有）"""
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
                    return
            except Exception:
                continue

    def _upload_video(self):
        """上传视频文件"""
        print("  📹 开始上传视频...")
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
                return
            title_input = self.page.query_selector('input[placeholder*="标题"]')
            if title_input:
                print("  ✅ 视频上传完成（标题输入框已出现）")
                return
            # 检查错误信息
            error_text = self.page.query_selector('[class*="error"]:has-text("上传失败")')
            if error_text:
                raise RuntimeError("视频上传失败，页面显示错误信息")
            time.sleep(10)

        raise RuntimeError("视频上传超时（5 分钟）")

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
        """上传封面图片"""
        if not self.cover_path or not os.path.exists(self.cover_path):
            print("  ⚠️ 无封面文件，跳过封面上传")
            return

        print("  🖼️ 开始上传封面...")
        # 用 JS 精确匹配"添加封面"按钮
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
            if (!btn) return 'NO_BTN';
            btn.scrollIntoView({block: 'center'});
            var rect = btn.getBoundingClientRect();
            return JSON.stringify({
                status: 'FOUND',
                x: rect.x + rect.width / 2,
                y: rect.y + rect.height / 2
            });
        }""")
        import json as _json
        if res and "FOUND" in res:
            btn = _json.loads(res)
            # 用原生鼠标点击
            self.page.mouse.move(btn["x"], btn["y"])
            time.sleep(0.2)
            self.page.mouse.click(btn["x"], btn["y"])
            print("  ✅ 已点击添加封面按钮")
        else:
            print("  ⚠️ 未找到添加封面按钮，尝试直接上传")

        time.sleep(1)

        # 在弹窗中找图片上传 input
        image_input = None
        for sel in [
            'input[type="file"][accept*="image"]',
            'input[type="file"][accept*="png"]',
            'input[type="file"][accept*="jpg"]',
        ]:
            image_input = self.page.query_selector(sel)
            if image_input:
                break

        if image_input:
            # 让 input 可见
            image_input.evaluate("""el => {
                el.style.display = 'block';
                el.style.visibility = 'visible';
                el.style.opacity = '1';
                el.style.position = 'fixed';
                el.style.top = '0';
                el.style.left = '0';
                el.style.zIndex = '99999';
            }""")
            time.sleep(0.3)
            image_input.set_input_files(self.cover_path)
            self.page.evaluate("""() => {
                const inputs = document.querySelectorAll('input[type="file"]');
                for (const input of inputs) {
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }""")
            time.sleep(2)
            # 点击"完成"按钮
            self._handle_confirm_dialog()
            print("  ✅ 封面已上传")
        else:
            print("  ⚠️ 未找到封面上传 input，跳过")

    def _fill_title(self):
        """填写标题"""
        print("  ✏️ 填写标题...")
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
                return
            except Exception as e:
                if attempt < 4:
                    time.sleep(2)
                    continue
                raise

    def _fill_tags(self):
        """填写标签（逐个输入后按 Enter）"""
        print(f"  🏷️ 填写标签（{len(self.tags)} 个）...")
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
                        return
                    # JS 赋值后验证未通过，尝试 keyboard.type 兜底
                    print("  ⚠️ JS 赋值验证未通过，尝试 keyboard.type 兜底...")
                    editor = self.page.query_selector('.ql-editor[contenteditable="true"]')
                    if editor:
                        editor.click()
                        self.page.keyboard.type(self.description, delay=15)
                        time.sleep(1)
                        print(f"  ✅ 简介已填写（keyboard.type，{len(self.description)} 字）")
                        return
                else:
                    # 兜底：找 textarea
                    textarea = self.page.query_selector('textarea')
                    if textarea:
                        textarea.fill(self.description)
                        print(f"  ✅ 简介已填写（textarea，{len(self.description)} 字）")
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
        if res2 != "SELECTED":
            print("  ⚠️ 未找到 AI 声明选项，跳过")

    def _select_district(self):
        """选择分区：资讯（JS 点击 select-controller→选"资讯"，与参考项目一致）"""
        print("  📂 选择分区...")
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
        if res2 == "NOT_FOUND":
            print("  ⚠️ 未找到分区选择器，跳过")

    def _submit(self):
        """点击投稿按钮提交"""
        print("  📤 提交投稿...")
        # 先关闭可能存在的弹窗（调用两次，可能有多层弹窗）
        print("  🔍 检查并关闭已有弹窗...")
        self._handle_confirm_dialog()
        time.sleep(1)
        self._handle_confirm_dialog()
        time.sleep(1)

        # 找投稿按钮
        submit_selectors = [
            'button:has-text("立即投稿")',
            'button:has-text("投稿")',
            '.submit-btn',
            '[class*="submit"]',
        ]
        submit_btn = None
        for sel in submit_selectors:
            submit_btn = self.page.query_selector(sel)
            if submit_btn:
                break

        if not submit_btn:
            raise RuntimeError("未找到投稿按钮")

        # 检查是否 disabled
        is_disabled = submit_btn.evaluate("el => el.disabled || el.classList.contains('disabled')")
        if is_disabled:
            # 检查表单是否有未填项
            form_errors = self._check_form_errors()
            if form_errors:
                raise RuntimeError(f"投稿按钮禁用，表单未填完整: {form_errors}")
            raise RuntimeError("投稿按钮处于禁用状态，可能表单未填完整")

        # 用原生鼠标点击（JS click 不能触发 React onClick）
        box = submit_btn.bounding_box()
        if box:
            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2
            self.page.mouse.move(cx, cy)
            time.sleep(0.2)
            self.page.mouse.click(cx, cy)
            print("  🖱️ 投稿按钮已点击")
        else:
            submit_btn.click()

        time.sleep(3)
        # 处理二次确认弹窗
        self._handle_confirm_dialog()

        # 等待 URL 跳转
        deadline = time.time() + 30
        while time.time() < deadline:
            url = self.page.url
            if "/video/manage" in url or "/platform/edit" in url:
                print("  ✅ 投稿已提交")
                return
            # 检测错误提示（toast / 表单验证）
            error_msg = self._check_submit_errors()
            if error_msg:
                raise RuntimeError(f"投稿提交失败: {error_msg}")
            time.sleep(2)

        # 未检测到跳转，再检查是否有错误
        error_msg = self._check_submit_errors()
        if error_msg:
            raise RuntimeError(f"投稿提交失败（未跳转）: {error_msg}")

        # 无跳转也无错误，可能投稿在后台处理中，继续轮询 BV 号
        print("  ⚠️ 未检测到 URL 跳转，但未发现错误提示，继续轮询 BV 号")

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
        """轮询个人空间获取 BV 号（仅按标题匹配，避免误匹配其他视频）"""
        print("  🔍 轮询个人空间获取 BV 号...")
        title_prefix = self.title[:8] if len(self.title) >= 8 else self.title

        # 优先从当前页面 URL 提取 BV（提交成功后可能跳转到投稿管理页）
        for attempt in range(3):
            try:
                url = self.page.url
                bvid = self._extract_bvid(url)
                if bvid:
                    print(f"  ✅ 从当前页面 URL 获取 BV 号: {bvid}")
                    return bvid
            except Exception:
                pass
            time.sleep(3)

        deadline = time.time() + 600  # 10 分钟
        while time.time() < deadline:
            try:
                uid = self._get_uid()
                if uid:
                    space_url = self.SPACE_URL_TEMPLATE.format(uid=uid)
                    space_page = self.context.new_page()
                    space_page.goto(space_url, wait_until="domcontentloaded", timeout=60000)
                    time.sleep(3)

                    # 查找标题匹配的视频链接（仅按标题前缀匹配，不匹配任意 /BV 链接）
                    links = space_page.query_selector_all("a[href*='/video/BV']")
                    match_count = 0
                    for link in links:
                        href = link.get_attribute("href") or ""
                        link_text = (link.inner_text() or "").strip()
                        # 仅按标题前缀匹配，避免误匹配个人空间里的其他视频
                        if title_prefix in link_text:
                            bvid = self._extract_bvid(href)
                            if bvid:
                                match_count += 1
                                space_page.close()
                                print(f"  ✅ 已获取 BV 号: {bvid}（标题匹配）")
                                return bvid
                    if match_count == 0 and links:
                        print(f"  ⏳ 个人空间有 {len(links)} 个视频，暂无标题匹配「{title_prefix}」的，继续轮询...")
                    space_page.close()
            except Exception:
                pass
            time.sleep(60)

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
