"""环节3a：Pexels 图片搜索与下载

双通道下载策略：
- API 通道（主）：PexelsApiClient 调用官方 REST API，无反爬、无 Chrome 依赖、
  结构化元数据可下载前过滤。
- 浏览器通道（兜底）：Selenium headless Chrome 访问搜索页，解析图片 URL 下载。
  API 不可用（无 key / 失败 / 限流）时自动回退。
"""

import os
import re
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def _create_driver(driver_path: str = None, page_load_timeout: int = 30):
    """创建 Selenium WebDriver

    Args:
        driver_path: ChromeDriver 路径，None 则自动查找
        page_load_timeout: 页面加载硬超时（秒），避免 driver.get() 无限挂起

    Returns:
        WebDriver 实例
    """
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
    )
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--lang=en-US")

    # 去掉「正受自动化软件控制」提示和自动化扩展痕迹，降低被判定为爬虫的概率
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if driver_path:
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=options)
    else:
        driver = webdriver.Chrome(options=options)

    # 抹掉 navigator.webdriver 标记
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
    except Exception:
        pass

    # 设置页面加载硬超时，防止 driver.get() 在网络异常时无限挂起
    driver.set_page_load_timeout(page_load_timeout)
    driver.set_script_timeout(10)

    return driver


# Pexels 反爬中间页的特征标题
_BLOCK_MARKERS = (
    "请稍候", "just a moment", "attention required", "access denied",
    "verify you are human", "checking your browser", "请稍等",
)


def _page_blocked(driver) -> bool:
    """判断当前页面是否是反爬中间页

    Args:
        driver: WebDriver 实例

    Returns:
        True 表示被拦截
    """
    try:
        title = (driver.title or "").lower()
    except Exception:
        return True
    return any(marker in title for marker in _BLOCK_MARKERS)


def _wait_for_results(driver, timeout: float = 20.0) -> bool:
    """轮询等待搜索结果真正加载

    Pexels 在连续搜索时会先返回「请稍候…」反爬中间页，
    几十秒后才放出真实结果。这里持续轮询页面状态。

    Args:
        driver: WebDriver 实例
        timeout: 最长等待秒数

    Returns:
        True 表示拿到真实搜索结果
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _page_blocked(driver):
            try:
                if "images.pexels.com" in driver.page_source:
                    return True
            except Exception:
                pass
        time.sleep(1.0)
    try:
        return (not _page_blocked(driver)) and "images.pexels.com" in driver.page_source
    except Exception:
        return False


class PexelsSession:
    """Pexels 抓取会话

    持有一个可重建的 Selenium 驱动。

    为什么需要重建：
    实测 Pexels 的反爬拦截是「按会话」生效的——同一个 Chrome 会话里连续搜索，
    第二次开始就会返回「请稍候…」中间页，且刷新/等 5 分钟都不会恢复；
    而换一个新的 Chrome 会话立刻就能拿到结果。因此被拦截时直接重建会话。
    """

    def __init__(self, driver_path: str = None, page_load_timeout: int = 30,
                 driver=None):
        self.driver_path = driver_path
        self.page_load_timeout = page_load_timeout
        self._driver = driver
        self._externally_owned = driver is not None

    @property
    def driver(self):
        if self._driver is None:
            self._driver = _create_driver(
                self.driver_path, page_load_timeout=self.page_load_timeout
            )
            self._externally_owned = False
        return self._driver

    def reset(self):
        """丢弃当前会话，创建一个新的 Chrome 实例"""
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None
        self._externally_owned = False
        return self.driver

    def close(self):
        if self._driver is None or self._externally_owned:
            self._driver = None
            return
        try:
            self._driver.quit()
        except Exception:
            pass
        self._driver = None


class PexelsApiClient:
    """Pexels 官方 API 客户端

    使用 Pexels 公开 REST API 搜索和下载图片，无需浏览器。
    相比 Selenium 方案：无反爬、无 Chrome 依赖、结构化元数据、下载前即可过滤。

    API 文档：https://www.pexels.com/api/documentation/
    认证：请求头携带 Authorization: <api_key>
    速率限制：25,000 次/月（响应头 x-ratelimit-* 可见）
    """

    BASE_URL = "https://api.pexels.com/v1"

    def __init__(self, api_key: str, timeout: int = 30):
        """初始化 API 客户端

        Args:
            api_key: Pexels API key
            timeout: HTTP 请求超时（秒）
        """
        self.api_key = api_key
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["Authorization"] = api_key

    def search_photos(
        self,
        query: str,
        orientation: str = None,
        per_page: int = 80,
        size: str = "large",
    ) -> list:
        """搜索 Pexels 图片

        调用 GET /v1/search，返回结构化 JSON 结果。

        Args:
            query: 搜索关键词（英文效果最好）
            orientation: 方向过滤，"landscape" / "portrait" / "square"，None 不过滤
            per_page: 每页数量，最多 80
            size: 图片尺寸，"large"（原图）/ "medium" / "small"

        Returns:
            照片字典列表，每项含 id/width/height/src/photographer 等字段
        """
        params = {
            "query": query,
            "per_page": min(per_page, 80),
            "size": size,
        }
        if orientation:
            params["orientation"] = orientation

        resp = self._session.get(
            f"{self.BASE_URL}/search", params=params, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("photos", [])

    def get_photo(self, photo_id: int) -> dict:
        """获取单张图片的详细信息

        Args:
            photo_id: Pexels 图片 ID

        Returns:
            照片字典
        """
        resp = self._session.get(
            f"{self.BASE_URL}/photos/{photo_id}", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    def close(self):
        """关闭 HTTP 会话"""
        try:
            self._session.close()
        except Exception:
            pass


def _save_and_validate_image(
    src_url: str,
    output_dir: str,
    index: int,
    orientation: str,
    referer: str = "",
    seen_filenames: set = None,
    max_retries: int = 2,
) -> str:
    """下载单张图片并完成校验、压缩，返回成功保存的路径

    从 API 或浏览器提取的图片 URL 通用处理逻辑，供两种下载通道复用。
    失败返回空字符串。

    Args:
        src_url: 图片 URL
        output_dir: 保存目录
        index: 序号（用于文件名）
        orientation: 期望方向
        referer: Referer 头
        seen_filenames: 已用文件名集合，避免重复
        max_retries: 下载重试次数

    Returns:
        成功保存的文件路径，失败返回空字符串
    """
    if seen_filenames is None:
        seen_filenames = set()

    ext = ".jpg"
    if ".png" in src_url.lower():
        ext = ".png"
    filename = f"img_{index}_{random.randint(1000, 9999)}{ext}"
    save_path = os.path.join(output_dir, filename)

    if filename in seen_filenames:
        return ""
    seen_filenames.add(filename)

    # 下载（API 和浏览器 URL 都在 images.pexels.com CDN，下载逻辑一致）
    if not _download_image(src_url, save_path, referer=referer, max_retries=max_retries):
        return ""

    # 方向/尺寸校验：不匹配则删除并跳过
    if not _check_orientation(save_path, orientation):
        try:
            os.remove(save_path)
        except OSError:
            pass
        print(f"    ⚠️ 不符合要求（方向或尺寸），跳过: {filename}")
        return ""

    # 压缩图片：限制最大边为 800px，避免 CLIP 编码和多模态评审内存溢出
    try:
        img = Image.open(save_path)
        img = img.convert("RGB")
        w, h = img.size
        max_side = 800
        if max(w, h) > max_side:
            ratio = max_side / max(w, h)
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        img.save(save_path, "JPEG", quality=85)
    except Exception as e:
        print(f"    ⚠️ 图片压缩失败（使用原始图片）: {e}")

    print(f"    ✅ 下载: {filename}")
    return save_path


def _download_via_api(
    keywords: list,
    output_dir: str,
    max_count: int,
    api_key: str,
    orientation: str = "landscape",
    timeout: int = 30,
) -> list:
    """通过 Pexels API 下载候选图片

    主下载通道：调用 API 搜索，利用响应中的 width/height 元数据
    在下载前过滤方向和尺寸，减少无效下载。

    Args:
        keywords: 搜索关键词列表
        output_dir: 图片保存目录
        max_count: 最多下载的图片数量
        api_key: Pexels API key
        orientation: 图片方向
        timeout: HTTP 请求超时

    Returns:
        成功下载的图片路径列表
    """
    os.makedirs(output_dir, exist_ok=True)
    downloaded_paths = []
    seen_filenames = set()
    client = PexelsApiClient(api_key, timeout=timeout)

    try:
        for keyword in keywords:
            if len(downloaded_paths) >= max_count:
                break

            search_term = (keyword or "").strip()
            if not search_term:
                continue
            search_term = re.sub(r"\s+", " ", search_term)

            print(f"  🌐 API 搜索 Pexels: {search_term} (方向: {orientation})")

            try:
                photos = client.search_photos(
                    query=search_term,
                    orientation=orientation,
                    per_page=max_count * 2,
                )
            except Exception as e:
                print(f"    ❌ API 搜索失败: {e}")
                continue

            if not photos:
                print(f"    ❌ API 未返回结果")
                continue

            # 下载前过滤：用 API 返回的 width/height 元数据过滤，省掉无效下载
            candidate_urls = []
            min_side = 200
            max_pixels = 50_000_000
            for photo in photos:
                w = photo.get("width", 0)
                h = photo.get("height", 0)
                if w < min_side or h < min_side:
                    continue
                if w * h > max_pixels:
                    continue
                # 方向过滤（API 已按 orientation 过滤，但做二次校验更保险）
                if orientation == "portrait":
                    if h <= w:
                        continue
                else:
                    if w <= h:
                        continue
                # 选择合适尺寸的 URL
                src = photo.get("src", {})
                # 优先用 landscape 或 large2x（足够清晰，但不会太大）
                url = src.get("landscape") or src.get("large2x") or src.get("original")
                if url:
                    candidate_urls.append(url)

            if not candidate_urls:
                print(f"    ❌ 元数据过滤后无可用图片")
                continue

            # 随机打乱，避免每次都下载同样顺序的图片
            random.shuffle(candidate_urls)

            # 并行下载
            max_workers = min(max_count, len(candidate_urls), 5)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {}
                for i, img_url in enumerate(candidate_urls):
                    idx = len(downloaded_paths) + i + 1
                    future = pool.submit(
                        _save_and_validate_image,
                        img_url, output_dir, idx, orientation, "", seen_filenames,
                    )
                    futures[future] = img_url

                for future in as_completed(futures):
                    if len(downloaded_paths) >= max_count:
                        break
                    try:
                        save_path = future.result()
                        if save_path:
                            downloaded_paths.append(save_path)
                    except Exception as e:
                        print(f"    ⚠️ 下载异常: {e}")

            # 关键词之间短暂停顿，避免连续请求
            time.sleep(random.uniform(0.3, 0.8))

    finally:
        client.close()

    return downloaded_paths


def _extract_image_urls(soup: BeautifulSoup, base_url: str) -> list:
    """从页面 HTML 中提取图片 URL

    Args:
        soup: BeautifulSoup 解析结果
        base_url: 当前页面 URL（用于补全相对路径）

    Returns:
        图片 URL 列表
    """
    urls = []

    # 策略1：从 img 标签的 srcset 中提取
    for img in soup.find_all('img'):
        srcset = img.get('srcset', '')
        if srcset:
            first_url = srcset.split(' ')[0]
            if first_url and ('images.pexels.com' in first_url or first_url.startswith('http')):
                if not first_url.startswith('http'):
                    first_url = base_url + first_url
                urls.append(first_url)
            continue

        # 策略2：从 data-src / data-lazy-src 提取
        for attr in ('data-src', 'data-lazy-src', 'data-original'):
            src = img.get(attr, '')
            if src and ('images.pexels.com' in src or src.startswith('http')):
                if not src.startswith('http'):
                    src = base_url + src
                urls.append(src)
                break

    # 策略3：直接从 HTML 中正则提取 images.pexels.com 的 URL
    html_str = str(soup)
    pexels_urls = re.findall(r'https?://images\.pexels\.com/[^\s"\'<>]+\.(?:jpg|jpeg|png)', html_str)
    urls.extend(pexels_urls)

    # 去重，保持顺序
    return list(dict.fromkeys(urls))


def _download_image(url: str, save_path: str, referer: str = "", max_retries: int = 2) -> bool:
    """下载单张图片并验证

    下载失败时自动重试，最多 max_retries 次。

    Args:
        url: 图片 URL
        save_path: 保存路径
        referer: Referer 头
        max_retries: 最大重试次数

    Returns:
        是否下载成功
    """
    for attempt in range(max_retries + 1):
        try:
            # 清理 Referer 中的非 ASCII 字符（HTTP 头仅支持 latin-1 编码）
            # Pexels 搜索 URL 可能包含中文关键词，需 URL 编码路径部分
            from urllib.parse import urlsplit, urlunsplit, quote
            if referer:
                parts = urlsplit(referer)
                safe_path = quote(parts.path, safe="/")
                referer = urlunsplit(parts._replace(path=safe_path))
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': referer,
            }
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()

            with open(save_path, 'wb') as f:
                f.write(resp.content)

            # 验证图片可正常打开
            img = Image.open(save_path)
            img.verify()
            img.close()
            return True
        except Exception as e:
            if attempt < max_retries:
                print(f"    ⚠️ 下载失败（第 {attempt+1} 次），重试中: {e}")
                time.sleep(2 * (attempt + 1))
            else:
                print(f"    ⚠️ 下载失败（已重试 {max_retries} 次）: {e}")
                # 清理残留的损坏文件
                try:
                    if os.path.exists(save_path):
                        os.remove(save_path)
                except OSError:
                    pass
                return False
    return False


def _check_orientation(image_path: str, orientation: str) -> bool:
    """检查图片方向和尺寸是否符合要求

    下载后二次校验，避免 Pexels 返回方向不一致或尺寸异常的图片。
    过滤掉过小的缩略图和过大的原图，避免后续处理崩溃。

    Args:
        image_path: 图片文件路径
        orientation: 期望方向，"landscape" 或 "portrait"

    Returns:
        是否符合要求（方向匹配且尺寸合理）
    """
    try:
        img = Image.open(image_path)
        w, h = img.size
        img.close()

        # 尺寸过滤：过小（缩略图）或过大（原图）都不可用
        min_side = 200       # 最小边不小于 200px
        max_pixels = 50_000_000  # 总像素不超过 5000 万
        if w < min_side or h < min_side:
            return False
        if w * h > max_pixels:
            return False

        # 方向过滤
        if orientation == "portrait":
            return h > w
        # 默认 landscape
        return w > h
    except Exception:
        return False


def download_pexels_images(
    keywords: list,
    output_dir: str,
    max_count: int = 5,
    driver_path: str = None,
    timeout: int = 20,
    page_load_timeout: int = 30,
    orientation: str = "landscape",
    driver=None,
    session=None,
    api_key: str = None,
) -> list:
    """从 Pexels 下载候选图片

    双通道下载策略：
    - API 通道（主）：有 api_key 时优先使用，无反爬、无 Chrome 依赖、
      结构化元数据可下载前过滤，速度快、可靠性高。
    - 浏览器通道（兜底）：API 不可用（无 key / 失败 / 限流）时自动回退到
      Selenium 方案。

    驱动管理：
    - 传入 session（PexelsSession）时复用，并可在被反爬拦截时自动重建会话
    - 传入 driver 时直接复用（不负责关闭）
    - 都不传时自动创建，并在结束时关闭（向后兼容）

    Args:
        keywords: 搜索关键词列表
        output_dir: 图片保存目录
        max_count: 最多下载的图片数量
        driver_path: ChromeDriver 路径
        timeout: 单次等待搜索结果就绪的超时（秒）
        page_load_timeout: 页面加载硬超时（秒），防止 driver.get() 挂起
        orientation: 图片方向，"landscape"（横屏，默认）或 "portrait"（竖屏）
        driver: 已有的 Selenium WebDriver 实例，None 则自动创建
        session: PexelsSession 实例（支持自动重建会话绕过反爬）
        api_key: Pexels API key，有则优先用 API 下载，无或失败时回退浏览器

    Returns:
        成功下载的图片路径列表
    """
    os.makedirs(output_dir, exist_ok=True)
    downloaded_paths = []

    # API 通道（主）：有 key 时优先使用
    if api_key:
        print(f"  🔑 使用 Pexels API 下载（API 优先，浏览器兜底）")
        try:
            downloaded_paths = _download_via_api(
                keywords, output_dir, max_count, api_key, orientation, timeout,
            )
        except Exception as e:
            print(f"  ⚠️ API 下载异常，回退到浏览器方案: {e}")
            downloaded_paths = []

        if downloaded_paths:
            return downloaded_paths

        # API 未下载到图片（失败或无结果），回退浏览器
        print(f"  🔄 API 未获取到图片，回退到浏览器下载...")

    # 浏览器通道（兜底）
    seen_filenames = set()

    # 会话/驱动生命周期管理
    owns_session = False
    if session is None:
        if driver is not None:
            session = PexelsSession(driver_path, page_load_timeout, driver=driver)
        else:
            session = PexelsSession(driver_path, page_load_timeout)
            owns_session = True

    try:
        for keyword in keywords:
            if len(downloaded_paths) >= max_count:
                break

            # 保留完整关键词（多词短语检索效果更好），并做 URL 编码
            from urllib.parse import quote
            search_term = (keyword or "").strip()
            if not search_term:
                continue
            search_term = re.sub(r"\s+", " ", search_term)

            url = (f"https://www.pexels.com/search/{quote(search_term, safe='')}/"
                   f"?size=large&orientation={orientation}")
            print(f"  🌐 搜索 Pexels: {search_term} (方向: {orientation})")

            # 反爬重试：Pexels 会先返回「请稍候…」中间页
            # 实测发现：拦截是按「会话」生效的，重建 Chrome 会话即可立即恢复，
            # 所以这里在被拦截时直接重建会话（而不是傻等）。
            ok = False
            for attempt in range(3):
                current = session.driver
                try:
                    current.get(url)
                except Exception as e:
                    print(f"    ⏳ 页面加载失败: {str(e)[:80]}")

                if _wait_for_results(current, timeout=timeout):
                    ok = True
                    break

                wait = 2 + attempt * 2 + random.uniform(0, 1.5)
                print(f"    ⏳ 命中反爬中间页，重建会话 {wait:.0f}s 后重试"
                      f"（{attempt + 1}/3）")
                time.sleep(wait)
                session.reset()

            if not ok:
                print(f"    ❌ 多次重试仍被拦截，跳过此关键词")
                continue

            soup = BeautifulSoup(session.driver.page_source, 'html.parser')
            image_urls = _extract_image_urls(soup, url)

            if not image_urls:
                print(f"    ❌ 未找到图片链接")
                continue

            # 随机打乱后下载
            random.shuffle(image_urls)

            # 并行下载候选图片（网络 I/O 密集，并发显著提速）
            def _download_one(img_url, idx):
                """下载单张图片并校验，返回 (save_path, ok)"""
                ext = ".jpg"
                if ".png" in img_url.lower():
                    ext = ".png"
                filename = f"img_{idx}_{random.randint(1000, 9999)}{ext}"
                save_path = os.path.join(output_dir, filename)

                if filename in seen_filenames:
                    return save_path, False
                seen_filenames.add(filename)

                if not _download_image(img_url, save_path, referer=url):
                    return save_path, False

                # 方向/尺寸校验：不匹配则删除并跳过
                if not _check_orientation(save_path, orientation):
                    try:
                        os.remove(save_path)
                    except OSError:
                        pass
                    print(f"    ⚠️ 不符合要求（方向或尺寸），跳过: {filename}")
                    return save_path, False

                # 压缩图片：限制最大边为 800px，避免 CLIP 编码和多模态评审内存溢出
                try:
                    img = Image.open(save_path)
                    img = img.convert('RGB')
                    w, h = img.size
                    max_side = 800
                    if max(w, h) > max_side:
                        ratio = max_side / max(w, h)
                        new_size = (int(w * ratio), int(h * ratio))
                        img = img.resize(new_size, Image.LANCZOS)
                    img.save(save_path, 'JPEG', quality=85)
                except Exception as e:
                    print(f"    ⚠️ 图片压缩失败（使用原始图片）: {e}")

                print(f"    ✅ 下载: {filename}")
                return save_path, True

            # 最多并发下载 max_count 张，避免过多并发请求
            max_workers = min(max_count, len(image_urls), 5)
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {
                    pool.submit(_download_one, img_url, len(downloaded_paths) + i + 1): img_url
                    for i, img_url in enumerate(image_urls[:max_count * 2])
                }
                for future in as_completed(futures):
                    if len(downloaded_paths) >= max_count:
                        break
                    save_path, ok = future.result()
                    if ok:
                        downloaded_paths.append(save_path)

            # 关键词之间随机停顿，避免连续请求触发反爬
            time.sleep(random.uniform(1.5, 3.5))

    finally:
        if owns_session:
            session.close()

    return downloaded_paths
