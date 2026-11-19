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
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self.page = self.context.new_page()
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
        self.page.goto(self.UPLOAD_URL, wait_until="networkidle", timeout=30000)
        time.sleep(2)
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

        file_input.set_input_files(self.video_path)

        # 触发 React 事件（B站前端是 React，需要手动触发）
        self.page.evaluate("""() => {
            const inputs = document.querySelectorAll('input[type="file"]');
            for (const input of inputs) {
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.dispatchEvent(new Event('input', { bubbles: true }));
                const reactPropsKey = Object.keys(input).find(k => k.startsWith('__reactProps$'));
                if (reactPropsKey && input[reactPropsKey] && input[reactPropsKey].onChange) {
                    input[reactPropsKey].onChange({ target: input, currentTarget: input });
                }
            }
        }""")

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
        """处理提示弹窗（确认/关闭类）"""
        confirm_selectors = [
            'button:has-text("确认")',
            'button:has-text("确定")',
            'button:has-text("继续")',
        ]
        close_selectors = [
            'button:has-text("知道了")',
            'button:has-text("暂不设置")',
            'button:has-text("取消")',
            'button:has-text("关闭")',
        ]
        for sel in close_selectors + confirm_selectors:
            try:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    el.click(timeout=1500)
                    print("  💬 已处理提示弹窗")
                    time.sleep(1)
                    return
            except Exception:
                continue

    def _upload_cover(self):
        """上传封面图片"""
        if not self.cover_path or not os.path.exists(self.cover_path):
            print("  ⚠️ 无封面文件，跳过封面上传")
            return

        print("  🖼️ 开始上传封面...")
        # 点击"添加封面"按钮
        add_cover_selectors = [
            'button:has-text("添加封面")',
            '[class*="cover"]:has-text("添加")',
            'span:has-text("添加封面")',
        ]
        clicked = False
        for sel in add_cover_selectors:
            try:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    el.click(timeout=3000)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
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
            for sel in ['button:has-text("完成")', 'button:has-text("确定")', 'button:has-text("确认")']:
                try:
                    el = self.page.query_selector(sel)
                    if el and el.is_visible():
                        el.click(timeout=2000)
                        break
                except Exception:
                    continue
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
        """填写简介（Quill 富文本编辑器）"""
        print("  📝 填写简介...")
        for attempt in range(3):
            try:
                # 简介是 Quill 编辑器（contenteditable）
                editor = None
                for sel in [
                    '.ql-editor[contenteditable="true"]',
                    '[contenteditable="true"]',
                    '.ql-editor',
                ]:
                    editor = self.page.query_selector(sel)
                    if editor:
                        break

                if editor:
                    editor.click()
                    # 使用 keyboard 输入（Quill 需要模拟键盘事件）
                    self.page.keyboard.type(self.description, delay=10)
                else:
                    # 兜底：找 textarea
                    textarea = self.page.query_selector('textarea')
                    if textarea:
                        textarea.fill(self.description)

                print(f"  ✅ 简介已填写（{len(self.description)} 字）")
                return
            except Exception:
                if attempt < 2:
                    time.sleep(2)
                    continue
                print("  ⚠️ 简介填写失败，继续")

    def _select_ai_declaration(self):
        """选择创作声明：含 AI 生成内容"""
        print("  🤖 选择 AI 声明...")
        for sel in [
            'label:has-text("AI")',
            '[class*="ai"]:has-text("AI生成")',
            'label:has-text("含AI生成内容")',
        ]:
            try:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    el.click(timeout=2000)
                    print("  ✅ 已选择 AI 声明")
                    return
            except Exception:
                continue
        # 尝试点击 checkbox
        try:
            checkbox = self.page.query_selector('input[type="checkbox"]')
            if checkbox and checkbox.is_visible():
                checkbox.check(timeout=2000)
                print("  ✅ 已勾选 AI 声明复选框")
                return
        except Exception:
            pass
        print("  ⚠️ 未找到 AI 声明选项，跳过")

    def _select_district(self):
        """选择分区：资讯"""
        print("  📂 选择分区...")
        # 分区通常是下拉选择器
        try:
            district_input = self.page.query_selector(
                '[class*="district"] input, [class*="partition"] input, select'
            )
            if district_input:
                district_input.click()
                time.sleep(1)
                # 选择"资讯"
                for sel in ['li:has-text("资讯")', 'option:has-text("资讯")', '[role="option"]:has-text("资讯")']:
                    el = self.page.query_selector(sel)
                    if el:
                        el.click(timeout=2000)
                        print("  ✅ 已选择分区：资讯")
                        return
        except Exception:
            pass
        print("  ⚠️ 未找到分区选择器，跳过")

    def _submit(self):
        """点击投稿按钮提交"""
        print("  📤 提交投稿...")
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
            raise RuntimeError("投稿按钮处于禁用状态，可能表单未填完整")

        # 用原生鼠标点击（JS click 不能触发 React onClick）
        box = submit_btn.bounding_box()
        if box:
            self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            time.sleep(0.2)
            self.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        else:
            submit_btn.click()

        time.sleep(2)
        # 处理二次确认弹窗
        self._handle_confirm_dialog()

        # 等待 URL 跳转
        deadline = time.time() + 30
        while time.time() < deadline:
            url = self.page.url
            if "/video/manage" in url or "/platform/edit" in url:
                print("  ✅ 投稿已提交")
                return
            time.sleep(2)

        print("  ⚠️ 未检测到 URL 跳转，但投稿可能已提交，继续轮询 BV 号")

    def _wait_for_bvid(self):
        """轮询个人空间获取 BV 号"""
        print("  🔍 轮询个人空间获取 BV 号...")
        deadline = time.time() + 600  # 10 分钟
        while time.time() < deadline:
            try:
                # 获取当前页面中的用户 UID（从 Cookie 或页面）
                uid = self._get_uid()
                if uid:
                    space_url = self.SPACE_URL_TEMPLATE.format(uid=uid)
                    space_page = self.context.new_page()
                    space_page.goto(space_url, wait_until="networkidle", timeout=30000)
                    time.sleep(2)

                    # 查找标题匹配的视频链接
                    links = space_page.query_selector_all("a[href*='/video/BV']")
                    for link in links:
                        href = link.get_attribute("href") or ""
                        link_text = (link.inner_text() or "").strip()
                        if self.title[:10] in link_text or "/BV" in href:
                            bvid = self._extract_bvid(href)
                            if bvid:
                                space_page.close()
                                print(f"  ✅ 已获取 BV 号: {bvid}")
                                return bvid
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
