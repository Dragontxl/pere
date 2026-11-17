"""环节1：文章输入

支持三种方式：
1. 智能体生成（Agnes 3.0 Flash 根据话题生成文章）
2. 上传文件（读取 txt 文件）
3. 粘贴文本（通过系统编辑器输入）
"""

import html
import os
import sys
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox


def _clean_article(text: str) -> str:
    """清洗文章文本，解码 HTML 实体

    网页复制粘贴的文章常带有 HTML 实体（如 &#x20; 表示空格），
    这些实体会被 TTS 逐字朗读、在字幕中显示为字面字符。
    在此处统一解码，确保文本干净地进入后续流程。

    Args:
        text: 原始文章文本

    Returns:
        解码 HTML 实体后的文章文本
    """
    if not text:
        return text
    return html.unescape(text)


def get_article_from_ai(client, topic: str, model: str = "agnes-3.0-flash") -> str:
    """用 Agnes 3.0 Flash 智能体生成文章

    Args:
        client: Agnes 客户端
        topic: 话题要求
        model: 模型名称

    Returns:
        生成的文章
    """
    prompt = (
        f"请根据以下话题要求写一篇文章，文章要有标题，标题自占一段。\n"
        f"话题要求：{topic}\n"
        f"请保持创意，标题两边不要有特殊符号。"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return _clean_article(response.choices[0].message.content.strip())


def get_article_from_file(file_path: str) -> str:
    """从文件读取文章

    Args:
        file_path: 文件路径

    Returns:
        文章内容
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return _clean_article(f.read())


def get_article_from_paste() -> str:
    """粘贴文本输入（使用系统默认编辑器）

    Returns:
        粘贴的文章内容
    """
    temp_file = "temp_article.txt"
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write("")

    editor = os.getenv('EDITOR', 'notepad' if os.name == 'nt' else 'vim')
    subprocess.call([editor, temp_file])

    with open(temp_file, "r", encoding="utf-8") as f:
        content = f.read()

    os.remove(temp_file)
    return _clean_article(content)


def select_and_get_article(client=None, model: str = "GLM-4-Flash-250414") -> str:
    """交互式获取文章，显示选择对话框

    Args:
        client: 智谱AI客户端（用于智能体生成）
        model: 模型名称

    Returns:
        文章内容
    """
    choice = messagebox.askyesnocancel(
        "文章输入",
        "点击「是」使用智能体生成\n点击「否」选择文件或粘贴\n点击「取消」退出",
        icon="question"
    )

    if choice is None:
        sys.exit(0)
    elif choice:
        topic = input("请输入话题要求: ")
        if not topic.strip():
            print("❌ 话题要求不能为空")
            sys.exit(1)
        return get_article_from_ai(client, topic, model)
    else:
        root = tk.Tk()
        root.withdraw()
        choice = messagebox.askquestion(
            "文章来源",
            "选择「是」上传文件，选择「否」粘贴文本",
            icon="question"
        )
        root.destroy()

        if choice == "yes":
            file_path = filedialog.askopenfilename(
                title="选择文本文件",
                filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
            )
            if file_path:
                return get_article_from_file(file_path)
            else:
                print("❌ 未选择文件")
                sys.exit(1)
        else:
            article = get_article_from_paste()
            if not article.strip():
                print("❌ 未输入内容")
                sys.exit(1)
            return article
