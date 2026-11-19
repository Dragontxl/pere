"""环节6d：视频封面生成

在最终视频产出后，以项目名称为关键词从 Pexels 下载匹配图片，
按视频实际宽高比例裁剪（cover 模式），并将项目名称以醒目文字
（半透明深色底条 + 白色描边）叠加到图片上，输出与视频比例一致
的封面图。

封面生成失败不会阻断视频产出：任何异常仅记录日志并返回 None。
"""

import os
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .video_merger import FFMPEG_EXE, FFPROBE_EXE

# Windows 常见中文字体路径映射（与 subtitle_overlay 一致，保证中文渲染）
_FONT_PATHS = {
    "SimHei": "C:/Windows/Fonts/simhei.ttf",
    "Microsoft YaHei": "C:/Windows/Fonts/msyh.ttc",
    "Arial": "C:/Windows/Fonts/arial.ttf",
}

# Linux（CI runner）常见中文字体候选
_LINUX_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _resolve_font_path() -> str | None:
    """解析可用的中文字体文件路径（Windows 优先，CI Linux 兜底）"""
    for path in _FONT_PATHS.values():
        if os.path.exists(path):
            return path
    for path in _LINUX_FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _probe_video_dimensions(video_path: str) -> tuple[int, int] | None:
    """探测视频的宽高，用于确定封面比例

    优先用 ffprobe 获取精确宽高；失败时回退 ffmpeg -i 解析。

    Returns:
        (width, height)，探测失败返回 None
    """
    # ffprobe 精确探测
    if FFPROBE_EXE:
        try:
            result = subprocess.run(
                [FFPROBE_EXE, "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=15,
            )
            parts = result.stdout.strip().split(",")
            if len(parts) >= 2:
                w, h = int(parts[0]), int(parts[1])
                if w > 0 and h > 0:
                    return w, h
        except Exception:
            pass

    # ffmpeg -i 兜底解析（CI 上 ffprobe 缺失时使用）
    try:
        result = subprocess.run(
            [FFMPEG_EXE, "-hide_banner", "-i", video_path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        m = re.search(r",\s*(\d{2,5})x(\d{2,5})\s", result.stderr or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass

    return None


def _target_size(video_path: str, orientation: str) -> tuple[int, int]:
    """计算封面目标尺寸

    优先按视频实际宽高（归一化到最大边不超过 1280，保持比例）；
    探测不到时按方向用标准比例：landscape → 1280×720，portrait → 720×1280。
    """
    dims = _probe_video_dimensions(video_path)
    if dims:
        w, h = dims
        if max(w, h) > 1280:
            scale = 1280 / max(w, h)
            w, h = max(1, round(w * scale)), max(1, round(h * scale))
        return w, h
    if orientation == "portrait":
        return 720, 1280
    return 1280, 720


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """按像素宽度对文本做换行（按字符累加，兼容中文）"""
    lines = []
    for raw_line in text.split("\n"):
        if raw_line == "":
            lines.append("")
            continue
        cur = ""
        for ch in raw_line:
            test = cur + ch
            if font.getlength(test) <= max_width or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def generate_cover_image(
    project_name: str,
    video_path: str,
    output_dir: str,
    api_key: str = None,
    orientation: str = "landscape",
) -> str | None:
    """生成视频封面

    以 project_name 为关键词从 Pexels 下载图片，按视频比例裁剪，
    叠加醒目的项目名称文字，输出 cover.jpg。

    Args:
        project_name: 项目名称（作为搜索关键词和叠加文字）
        video_path: 最终视频路径（用于探测比例）
        output_dir: 封面输出目录
        api_key: Pexels API key，None 时下载器会自动回退浏览器通道
        orientation: 方向兜底，"landscape" / "portrait"

    Returns:
        封面图片路径；失败返回 None（不抛异常，不阻断视频产出）
    """
    from core.asset_matcher.pexels_downloader import download_pexels_images

    project_name = (project_name or "").strip()
    if not project_name:
        print("  ⚠️ 封面生成跳过：项目名称为空")
        return None

    try:
        target_w, target_h = _target_size(video_path, orientation)
        download_orientation = "portrait" if target_h > target_w else "landscape"
        print(f"  🖼️ 封面目标尺寸: {target_w}×{target_h}（方向: {download_orientation}）")

        cover_dir = Path(output_dir)
        cover_dir.mkdir(parents=True, exist_ok=True)
        download_dir = str(cover_dir / "cover_src")
        os.makedirs(download_dir, exist_ok=True)

        # 以项目名称为关键词下载候选图片
        print(f"  📥 以「{project_name}」为关键词下载封面候选图...")
        downloaded = download_pexels_images(
            keywords=[project_name],
            output_dir=download_dir,
            max_count=3,
            orientation=download_orientation,
            api_key=api_key,
        )

        if not downloaded:
            print("  ⚠️ 未下载到封面候选图，封面生成跳过")
            return None

        src_path = downloaded[0]
        if not os.path.exists(src_path):
            print("  ⚠️ 封面候选图文件不存在，封面生成跳过")
            return None

        with Image.open(src_path) as src_img:
            src_img = src_img.convert("RGB")

        # cover 模式裁剪：缩放使图片覆盖目标区域，再中心裁剪，保证比例一致
        src_ratio = src_img.width / src_img.height
        target_ratio = target_w / target_h
        if src_ratio > target_ratio:
            # 源图更宽：按高度缩放，裁左右
            new_h = target_h
            new_w = round(target_h * src_ratio)
        else:
            # 源图更高：按宽度缩放，裁上下
            new_w = target_w
            new_h = round(target_w / src_ratio)
        src_img = src_img.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        cover_img = src_img.crop((left, top, left + target_w, top + target_h))

        # 叠加项目名称文字
        draw = ImageDraw.Draw(cover_img, "RGBA")
        font_path = _resolve_font_path()
        font_size = max(28, min(target_w // 8, 96))
        try:
            font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()

        lines = _wrap_text(project_name, font, target_w - 80)
        line_height = font_size + 10
        block_h = len(lines) * line_height
        block_w = max((font.getlength(line) for line in lines), default=0)

        # 文字块居中偏下（封面构图常用位置）
        block_x = (target_w - block_w) // 2
        block_y = target_h - block_h - int(target_h * 0.08)

        # 半透明深色底条：保证文字在任意背景上都醒目
        padding_x = 24
        padding_y = 12
        band_x0 = block_x - padding_x
        band_y0 = block_y - padding_y
        band_x1 = block_x + block_w + padding_x
        band_y1 = block_y + block_h + padding_y
        draw.rounded_rectangle(
            [band_x0, band_y0, band_x1, band_y1],
            radius=12,
            fill=(0, 0, 0, 160),
        )

        # 绘制文字：白色填充 + 黑色描边，醒目
        y = block_y
        stroke_w = max(2, font_size // 12)
        for line in lines:
            draw.text(
                (block_x, y), line, font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke_w, stroke_fill=(0, 0, 0, 255),
            )
            y += line_height

        cover_path = str(cover_dir / "cover.jpg")
        cover_img.save(cover_path, "JPEG", quality=90)
        print(f"  ✅ 封面已生成: {cover_path}")
        return cover_path

    except Exception as e:
        print(f"  ⚠️ 封面生成失败（不影响视频产出）: {e}")
        import traceback
        traceback.print_exc()
        return None
