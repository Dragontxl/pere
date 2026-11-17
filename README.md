# 图文+Remotion 自动视频生成系统

从文章出发，自动生成带语音和字幕的解说视频。

## 技术路线

```
文章 → LLM 分镜 → 图片素材匹配下载 → Remotion 编码片段 → 综合决策 → 合成输出
```

**核心取舍**：仅使用图片素材（Pexels 来源，配 Ken Burns 动效）和 Remotion 编码视频片段，不使用 Pexels 视频片段，以降低内容匹配难度和合成复杂度。

## 功能模块

| 环节 | 模块 | 说明 |
|---|---|---|
| 1. 文章输入 | `core/article_input.py` | 智能体生成 / 上传文件 / 粘贴文本 |
| 2. 分镜生成 | `core/scene_generator.py` | GLM-4-Flash 将文章拆解为结构化镜头 |
| 3. 素材匹配 | `core/asset_matcher/` | Pexels 图片下载 + CLIP 相似度匹配 |
| 4. Remotion 分析 | `core/remotion_analyzer.py` | 判断镜头是否适合编码视频 |
| 5. 综合决策 | `core/decision_engine.py` | 决定每个镜头用图片还是 Remotion |
| 6. 视频合成 | `core/composer/` | Ken Burns 动效 + 语音 + 字幕拼接 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

编辑 `config/settings.json`，填入智谱 AI API Key 和其他参数。

### 3. 运行

**交互模式**（本地）：
```bash
python main.py
```

**非交互模式**（指定文章文件，适合 CI）：
```bash
python main.py --article-file article.txt
```

## 目录结构

```
pexel-remotion/
├── config/              # 配置文件
├── core/               # 核心模块
│   ├── article_input.py
│   ├── scene_generator.py
│   ├── asset_matcher/   # 素材下载与匹配
│   ├── remotion_analyzer.py
│   ├── decision_engine.py
│   └── composer/        # 视频合成
├── remotion/           # Remotion 项目（阶段三）
├── assets/             # 输出目录
├── main.py             # 主流程入口
└── requirements.txt
```

## 外部工具依赖

- **ffmpeg** — 视频处理（moviepy 依赖）
- **ImageMagick** — 字幕渲染（TextClip 依赖）
- **Chrome + ChromeDriver** — Pexels 图片抓取
- **Node.js** — Remotion 渲染（阶段三）
