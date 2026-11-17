"""通用工具函数"""

import json
import os
import re
from pathlib import Path


def load_config(config_name: str = "settings.json") -> dict:
    """加载配置文件

    Args:
        config_name: 配置文件名（settings.json 或 render_params.json）

    Returns:
        配置字典
    """
    config_path = Path(__file__).parent.parent / "config" / config_name
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir(path: str) -> str:
    """确保目录存在，不存在则创建

    Args:
        path: 目录路径

    Returns:
        目录路径
    """
    os.makedirs(path, exist_ok=True)
    return path


def detect_language(text: str) -> str:
    """检测文本主要语言

    Args:
        text: 输入文本

    Returns:
        'zh' 或 'en'
    """
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    non_chinese_chars = len(re.sub(r'[\u4e00-\u9fff]', '', text))

    if chinese_chars > non_chinese_chars * 0.5:
        return 'zh'
    return 'en'


def is_chinese(text: str) -> bool:
    """判断文本是否主要包含中文"""
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    return chinese > len(text) * 0.3


def clean_filename(name: str) -> str:
    """清理文件名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|\n\r]', '', name).strip()
