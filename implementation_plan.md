# 图文+Remotion 自动视频生成系统 — 实现计划

> **目标**：从文章出发，自动生成完整的带语音和字幕的解说视频。
> **技术路线**：文章 → 分镜 → 素材匹配下载（图片） → Remotion 编码片段 → 综合决策 → 合成输出
> **核心取舍**：仅使用**图片素材**（Pexels 等来源，配 Ken Burns 动效）和 **Remotion 编码视频**片段，**不使用 Pexels 视频片段**，以降低内容匹配难度和合成复杂度。

---

## 一、系统总览

### 1.1 整体流程

```
┌──────────────────────────────────────────────────────────────────────┐
│                            主流程编排                                 │
├────────────┬────────────────────────────────────────────────────────┤
│  环节1     │  文章输入（智能体生成 / 用户上传 / 用户粘贴）              │
│  环节2     │  LLM 分镜：文章 → 结构化镜头列表（JSON）                  │
│  环节3     │  素材匹配：为每个镜头从 Pexels 搜索并下载图片，           │
│            │  用 CLIP 初筛 + 多模态模型精评，选择匹配度最高的图片      │
│  环节4     │  Remotion 分析：判断哪些镜头适合编码视频实现             │
│  环节5     │  综合决策：决定每个镜头用图片还是 Remotion 片段          │
│  环节6     │  合成输出：拼接视频 + 语音合成 + 字幕叠加               │
└────────────┴────────────────────────────────────────────────────────┘
```

### 1.2 镜头实现方式决策

| 镜头类型 | 实现方式 | 示例 |
|---|---|---|
| 实景/风景/概念 | **图片** + Ken Burns 动效 | 森林晨光、海洋、城市 |
| 数据图表/信息图 | **Remotion** 动态生成 | 柱状图、折线图、数据展示 |
| 文字动画/关键词 | **Remotion** | 标题飞入、关键词高亮 |
| 流程图/结构图 | **Remotion** | 逐步展开的图形 |
| 转场/特效 | **Remotion** | 过渡动画、视觉特效 |

---

## 二、分阶段实施计划

采用三阶段递进策略，每阶段交付可运行的完整链路。

---

### 阶段一：核心链路验证（文章 → 分镜 → 图片素材 → 合成）

**目标**：跑通主链路，暂不引入 Remotion，所有镜头用图片实现。

#### 2.1.1 环节 1：文章输入

**状态**：✅ 已有基础，直接复用。

**实现要点**：
- 复用现有 `functions.py` 的 `make_client()` 和 `input_content()`
- 提供三种输入方式：GLM-4-Flash 智能体生成、上传 txt 文件、粘贴文本
- 复用现有 Tkinter 弹窗交互逻辑

**依赖**：`zhipuai`、`functions.py`、`api.py`

---

#### 2.1.2 环节 2：LLM 分镜生成

**状态**：🆕 新增功能，本阶段核心。

**实现要点**：

设计结构化分镜输出，让 LLM 将文章拆解为镜头列表，输出 JSON：

```json
{
  "scenes": [
    {
      "scene_id": 1,
      "visual_description": "清晨的森林，阳光透过树叶洒落，雾气弥漫",
      "search_keywords": ["forest morning sunlight", "foggy forest", "misty woods"],
      "on_screen_text": "在遥远的东方，有一片古老的森林",
      "duration": 4.5,
      "visual_type": "landscape",
      "needs_effect": false
    }
  ]
}
```

**字段说明**：

| 字段 | 用途 |
|---|---|
| `scene_id` | 镜头序号，用于排序和拼接 |
| `visual_description` | 给多模态模型做内容匹配分析的依据 |
| `search_keywords` | 给 Pexels 搜索用，中英双语，多个候选词 |
| `on_screen_text` | 该镜头的解说文本，用于字幕 |
| `duration` | 预估时长（后续根据语音时长对齐调整） |
| `visual_type` | 镜头类型，辅助环节 5 决策 |
| `needs_effect` | 是否需要特殊效果 |

**`visual_type` 枚举值**：
- `landscape` — 自然风光/实景
- `concept` — 概念/抽象
- `data_visual` — 数据可视化
- `text_animation` — 文字动画
- `diagram` — 流程图/结构图
- `portrait` — 人物/肖像
- `event` — 事件/动作场景

**Prompt 设计要点**：
- 明确要求只输出 JSON，不要解释
- 要求关键词中英双语，便于 Pexels 搜索
- `duration` 根据 `on_screen_text` 的字数合理预估（中文约 3-4 字/秒）
- 提供"重新生成"机制（复用现有脚本的弹窗逻辑）

**依赖**：`zhipuai`（GLM-4-Flash）、`re`、`json`

---

#### 2.1.3 环节 3a：Pexels 图片搜索与下载

**状态**：🔧 在现有 Selenium 抓取基础上扩展，从抓视频改为抓图片。

**实现要点**：

- 使用 Selenium headless Chrome 访问 Pexels 图片搜索页
- URL 格式：`https://www.pexels.com/search/{keyword}/?size=large`
- 解析页面中的图片 URL，随机选择下载
- 每个镜头下载 **多张候选图片**（建议 5-8 张），供后续匹配筛选
- 图片保存到临时目录，文件名含镜头序号

**下载策略**：
- 按 `search_keywords` 列表逐个尝试搜索，直到下载够候选图片
- 控制下载数量，避免过多浪费
- 下载后验证图片可正常打开（PIL 验证）

**依赖**：`selenium`、`requests`、`beautifulsoup4`、`PIL`

---

#### 2.1.4 环节 3b：图片内容匹配分析（CLIP 初版）

**状态**：🆕 本阶段核心难点。

**实现要点**：

**初版采用 CLIP 嵌入相似度匹配**，多模态大模型精评留到阶段二。

1. **模型加载**：使用 `open_clip` 或 `transformers` 的 CLIP 模型
2. **文本编码**：将 `visual_description` 编码为文本向量
3. **图片编码**：将每张候选图片编码为图像向量
4. **相似度计算**：计算每张图片与描述的余弦相似度
5. **选择**：取相似度最高的图片，记录匹配分数

**匹配流程**：
```
下载候选图片(5-8张)
  → CLIP 编码所有图片
  → 与 visual_description 计算相似度
  → 排序，取最高分
  → 记录匹配分数（用于环节5决策）
```

**匹配分数阈值**：初版设 0.25（CLIP 余弦相似度的常见阈值区间），后续根据实际效果调整。

**依赖**：`open_clip_torch` 或 `transformers`、`torch`、`PIL`

---

#### 2.1.5 环节 6a：图片 → 视频片段（Ken Burns 动效）

**状态**：🆕 新增功能。

**实现要点**：

将匹配的图片转换为带 Ken Burns 动效（缩放/平移）的视频片段：

1. **基础处理**：用 moviepy 加载图片，创建 `ImageClip`
2. **动效设计**（根据镜头类型选择）：
   - `landscape`/`concept`：缓慢缩放（zoom in 或 zoom out）
   - `portrait`：缓慢平移或轻微缩放
   - 使用 `resize` + `set_position` 实现平滑动效
3. **时长控制**：根据镜头 `duration` 设置片段时长
4. **输出格式**：统一编码为 libx264 / aac，与最终合成参数一致

**动效多样化策略**（避免单调）：
- 不同镜头使用不同的运动方向（放大、缩小、左移、右移、上移、下移）
- 根据 `scene_id` 奇偶交替选择方向，保证自然变化
- 远景镜头用慢速平移，特写镜头用放大

**依赖**：`moviepy`、`PIL`、`numpy`、`ffmpeg`

---

#### 2.1.6 环节 6b：语音合成

**状态**：✅ 已有基础，直接复用。

**实现要点**：
- 使用 edge-tts 合成全文语音，复用现有 `text_to_speech()` 函数
- 自动检测语言（中文用 `zh-CN-YunjianNeural`，英文用 `en-US-EricNeural`）
- 记录语音总时长，用于调整各镜头片段时长

**时长对齐**：
- 各镜头片段时长按 `duration` 占比分配语音总时长
- 确保所有片段时长之和 = 语音总时长

**依赖**：`edge-tts`、`asyncio`、`moviepy`

---

#### 2.1.7 环节 6c：视频拼接与字幕叠加

**状态**：🔧 在现有合并逻辑基础上扩展。

**实现要点**：

1. **拼接**：用 moviepy `concatenate_videoclips` 按镜头顺序拼接所有片段
2. **合并语音**：将语音音频叠加到拼接后的视频上
3. **字幕**：
   - 根据各镜头的 `on_screen_text` 和分配的时长，计算字幕时间轴
   - 字幕时间与画面一一对应，避免均匀分配的不精准问题
   - 使用 moviepy `TextClip` 叠加字幕
   - 中文用 SimHei 字体，英文用 Arial
4. **输出**：最终视频保存为 mp4

**字幕时间轴计算**：
```
每个镜头的字幕：
  start_time = 前序镜头时长之和
  end_time = start_time + 该镜头片段时长
  text = on_screen_text
```

**依赖**：`moviepy`、`ImageMagick`（TextClip 依赖）

---

#### 阶段一交付物

- [ ] 分镜生成模块（LLM Prompt + JSON 解析）
- [ ] Pexels 图片搜索下载模块
- [ ] CLIP 图片匹配模块
- [ ] Ken Burns 图片转视频模块
- [ ] 语音合成模块（复用）
- [ ] 视频拼接 + 字幕叠加模块
- [ ] 端到端可运行的主流程编排脚本
- [ ] 中间文件清理机制（复用现有逻辑）

---

### 阶段二：匹配质量提升 + 字幕优化

**目标**：提升图片匹配精度，优化字幕时间轴，完善兜底策略。

#### 2.2.1 多模态大模型精评

在 CLIP 初筛基础上，引入多模态大模型对候选图片做精准评分：

**流程升级**：
```
下载候选图片(5-8张)
  → CLIP 初筛（保留相似度 > 阈值的前3张）
  → 多模态大模型精评（对候选打分 0-100）
  → 选择最高分图片
```

**多模态模型选择**：
- 智谱 GLM-4V（与现有技术栈一致，推荐）
- 或 Gemini / GPT-4V（效果更优，成本更高）

**评分 Prompt 设计**：
```
请分析这张图片的内容，判断它与以下场景描述的匹配程度。
场景描述：{visual_description}
请给出 0-100 的匹配度评分，并简要说明理由。
```

**阈值标定**：根据实际效果调整，建议初始设 70 分。

**依赖**：`zhipuai`（GLM-4V）或对应多模态 API

---

#### 2.2.2 字幕时间轴优化

**当前问题**：阶段一按镜头时长均匀分配字幕，虽然比按句子均匀好，但仍可优化。

**优化方向**：
- 根据语音音频的实际停顿，微调字幕起止时间
- 可使用 whisper 对语音做时间戳对齐，获取每个句子的实际发音时间
- 字幕显示时间与音频实际发音时间对齐，提升体验

**依赖**：`whisper`（已有 `提取视频字幕.py` 可参考）

---

#### 2.2.3 无匹配素材兜底策略

**当前问题**：当 CLIP 和多模态模型都无法找到匹配度达标的图片时，如何处理。

**兜底策略**（按优先级）：

1. **放宽搜索**：使用更宽泛的关键词重新搜索下载
2. **AI 文生图补位**：使用智谱 CogView 或其他文生图模型，根据 `visual_description` 生成图片
3. **标记问题镜头**：记录未匹配的镜头，在日志中提示，最终可生成带占位图的视频供人工检查

**推荐**：优先实现 AI 文生图补位，用 `visual_description` 直接生成匹配图片，作为 Pexels 素材的可靠后备。

**依赖**：`zhipuai`（CogView）或对应文生图 API

---

#### 2.2.4 Ken Burns 动效优化

**优化方向**：
- 根据镜头内容类型，智能选择动效方向和速度
- 增加淡入淡出效果，避免硬切生硬
- 在不同镜头间使用转场效果（淡入、擦除等）

**依赖**：`moviepy`

---

#### 阶段二交付物

- [ ] 多模态大模型精评模块（CLIP 初筛 + 大模型精评）
- [ ] Whisper 语音时间戳对齐字幕
- [ ] AI 文生图兜底模块
- [ ] Ken Burns 动效优化与转场效果
- [ ] 匹配阈值标定与调优

---

### 阶段三：引入 Remotion 编码视频

**目标**：实现 Remotion 编码视频片段，完成图片/Remotion 双轨决策与合成。

#### 2.3.1 环境搭建

**Remotion 环境准备**：
- 安装 Node.js（如未安装）
- 创建 Remotion 项目：`npx create-video@latest`
- 配置渲染输出参数（分辨率、帧率、编码器），与 Python 端合成参数保持一致

**跨语言编排架构**：
```
Python 主流程
  ├── 调用 Node.js / Remotion 渲染片段
  │     └── 为每个 coding 镜头生成并执行 Remotion 代码
  │
  └── 接收 Remotion 输出的 mp4 片段
        └── 与图片片段一起拼接合成
```

**编排方式**：Python 通过 `subprocess` 调用 Node.js 命令，渲染完成后回收 mp4 文件。

---

#### 2.3.2 镜头分类规则与 Remotion 适用性判断

**规则定义**：

根据环节 2 的 `visual_type` 字段，判断是否适合 Remotion：

| visual_type | Remotion 适用 | 说明 |
|---|---|---|
| `data_visual` | ✅ 适合 | 图表、数据展示，Remotion 最佳场景 |
| `text_animation` | ✅ 适合 | 文字飞入、高亮等动画 |
| `diagram` | ✅ 适合 | 流程图、结构图逐步展开 |
| `landscape` | ❌ 不适合 | 用图片 + Ken Burns |
| `concept` | ❌ 不适合 | 用图片 |
| `portrait` | ❌ 不适合 | 用图片 |
| `event` | ❌ 不适合 | 用图片 |

**实现**：环节 4 读取 `visual_type`，输出每个镜头是否使用 Remotion 的标记。

---

#### 2.3.3 Remotion 代码自动生成

**核心难点**：为每个 coding 镜头自动生成可运行的 Remotion React 组件代码。

**实现思路**：
1. **模板化生成**：为每种 `visual_type` 预设 Remotion 组件模板
   - `data_visual`：柱状图/折线图动画模板
   - `text_animation`：文字飞入/高亮模板
   - `diagram`：流程图展开模板
2. **LLM 生成**：用 GLM-4 根据镜头描述，在模板基础上生成具体组件代码
3. **代码验证**：渲染前先做语法检查，渲染失败则回退到图片方案

**组件参数化**：
- 组件接收 `description`、`text`、`duration` 等参数
- 渲染时通过命令行或 JSON 配置文件传入

**渲染执行**：
```bash
npx remotion render <component> <output.mp4> --props=props.json
```

**依赖**：`remotion`、Node.js、`zhipuai`（代码生成）

---

#### 2.3.4 综合决策引擎（环节 5）

**决策逻辑**：

```
对每个镜头：

1. 如果 visual_type 属于 {data_visual, text_animation, diagram}
   → 使用 Remotion 编码视频

2. 否则，如果图片匹配分数 >= 阈值（如 70 分）
   → 使用图片 + Ken Burns 动效

3. 否则（图片不达标，且镜头不适合 Remotion）
   → 尝试 AI 文生图补位
   → 若仍失败，标记为问题镜头，使用占位图
```

**输出**：每个镜头的最终实现方式 + 素材路径/渲染产物路径。

**依赖**：纯 Python 逻辑，无额外依赖。

---

#### 2.3.5 Remotion 片段与图片片段统一合成

**实现要点**：
- Remotion 渲染输出的 mp4 片段，作为普通视频片段接入 moviepy 拼接流程
- **编码参数统一**：确保 Remotion 输出与图片片段的分辨率、帧率、编码器一致
  - 统一分辨率：如 1920×1080
  - 统一帧率：如 24fps
  - 统一编码：libx264 / aac
- 拼接流程与阶段一一致，无需额外修改

**参数一致性配置**：
在 Python 端和 Remotion 端分别配置相同的渲染参数，建议抽离为配置文件。

**依赖**：`moviepy`、`ffmpeg`

---

#### 阶段三交付物

- [ ] Remotion 项目环境搭建
- [ ] 镜头分类与 Remotion 适用性判断模块
- [ ] Remotion 组件模板库（data_visual / text_animation / diagram）
- [ ] LLM 自动生成 Remotion 代码模块
- [ ] Remotion 渲染执行与代码验证
- [ ] 综合决策引擎
- [ ] Remotion 片段与图片片段统一合成
- [ ] 端到端完整流程（图片 + Remotion 双轨）

---

## 三、项目结构规划

```
F:\Programs\pexel-remotion\
│
├── README.md                        # 项目说明
├── requirements.txt                 # Python 依赖
├── package.json                     # Node.js 依赖（阶段三）
│
├── config/
│   ├── settings.json                # 全局配置（API Key、路径、阈值等）
│   └── render_params.json           # 渲染参数（分辨率、帧率、编码）
│
├── main.py                          # 主流程编排入口
│
├── core/                           # 核心模块
│   ├── __init__.py
│   ├── article_input.py             # 环节1：文章输入
│   ├── scene_generator.py           # 环节2：LLM 分镜生成
│   ├── asset_matcher.py             # 环节3：素材下载与匹配分析
│   │   ├── pexels_downloader.py     #   Pexels 图片下载
│   │   ├── clip_matcher.py          #   CLIP 相似度匹配
│   │   └── multimodal_reviewer.py   #   多模态大模型精评（阶段二）
│   ├── remotion_analyzer.py         # 环节4：Remotion 适用性分析
│   ├── decision_engine.py           # 环节5：综合决策引擎
│   └── composer.py                  # 环节6：视频合成
│   │   ├── image_to_clip.py         #   图片 → Ken Burns 视频片段
│   │   ├── tts_synthesis.py         #   语音合成
│   │   ├── video_merger.py          #   视频拼接
│   │   └── subtitle_overlay.py      #   字幕叠加
│
├── remotion/                       # Remotion 项目（阶段三）
│   ├── templates/                  # 组件模板
│   │   ├── data_visual/
│   │   ├── text_animation/
│   │   └── diagram/
│   ├── render.js                   # 渲染脚本
│   └── scenes/                     # 自动生成的场景组件
│
├── assets/                         # 输出目录
│   └── (运行后自动生成)
│
├── temp/                           # 临时文件（运行后自动生成）
│
└── docs/
    └── implementation_plan.md      # 本文档
```

---

## 四、依赖清单

### 4.1 Python 依赖

```
zhipuai>=2.0.0           # 智谱 AI（GLM-4-Flash 分镜、GLM-4V 多模态、CogView 文生图）
edge-tts>=6.1.0          # 语音合成
moviepy>=1.0.3           # 视频处理
opencv-python>=4.8.0     # 图片处理
Pillow>=10.0.0           # 图片处理
selenium>=4.10.0         # Pexels 网页抓取
requests>=2.31.0         # HTTP 请求
beautifulsoup4>=4.12.0   # HTML 解析
torch>=2.0.0             # CLIP 模型
open_clip_torch>=2.20.0  # CLIP 模型（阶段一匹配）
transformers>=4.35.0     # 备选 CLIP 加载
whisper>=20231117        # 语音时间戳（阶段二字幕优化）
numpy>=1.24.0
```

### 4.2 Node.js 依赖（阶段三）

```
remotion>=4.0.0
```

### 4.3 外部工具

- **ffmpeg** — moviepy 依赖，需系统安装
- **ImageMagick** — moviepy TextClip 依赖，需系统安装并配置路径
- **Chrome + ChromeDriver** — Selenium 抓取 Pexels 所需
- **Node.js** — Remotion 运行环境（阶段三）

---

## 五、风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| LLM 分镜质量不稳定 | 镜头描述不准，影响后续匹配 | 精心设计 Prompt，提供重新生成机制，人工可介入编辑 |
| CLIP 匹配精度不足 | 选到不匹配的图片 | 阶段二引入多模态大模型精评；设置合理阈值；提供文生图兜底 |
| Pexels 反爬/限制 | 下载失败 | Selenium 伪装浏览器，控制请求频率，多关键词重试 |
| Ken Burns 动效单调 | 视觉疲劳 | 动效方向多样化，阶段二增加转场效果 |
| Remotion 代码生成不可用 | 渲染失败 | 代码模板化 + 语法验证，失败时回退到图片方案 |
| Remotion 与 Python 编码参数不一致 | 拼接出错 | 统一配置文件，渲染参数在两端保持一致 |
| 语音与画面时长不对齐 | 音画不同步 | 按镜头时长占比分配，阶段二用 whisper 微调 |
| 多模态模型调用成本 | 运营成本上升 | CLIP 初筛减少大模型调用次数，仅对候选图片精评 |

---

## 六、里程碑与时间规划

> 时间预估为参考，根据实际情况调整。

| 阶段 | 内容 | 预估周期 |
|---|---|---|
| **阶段一** | 核心链路：文章 → 分镜 → 图片素材 → 合成 | 2-3 周 |
| **阶段二** | 匹配质量提升 + 字幕优化 + 兜底策略 | 1-2 周 |
| **阶段三** | Remotion 编码视频 + 双轨决策 | 2-3 周 |

**阶段一细分**：
- 分镜生成模块：3-4 天
- Pexels 图片下载：2-3 天
- CLIP 匹配模块：2-3 天
- Ken Burns 图片转视频：2 天
- 拼接 + 字幕合成：2-3 天
- 端到端联调：2-3 天

---

## 七、验收标准

### 阶段一验收
- 输入一篇文章，系统能自动生成镜头列表
- 每个镜头能从 Pexels 下载候选图片并选出匹配度最高的
- 输出带语音和字幕的完整视频
- 视频中图片有 Ken Burns 动效，非静态展示
- 字幕与画面镜头对应，语音与画面同步

### 阶段二验收
- 多模态模型精评能显著提升匹配准确率
- 字幕时间与音频实际发音时间对齐
- 无匹配素材时能通过 AI 文生图兜底，不中断流程

### 阶段三验收
- 数据可视化、文字动画类镜头能通过 Remotion 渲染
- Remotion 片段与图片片段能无缝拼接
- 决策引擎能正确为每个镜头选择实现方式
- 最终视频视觉风格统一，无明显拼接痕迹

---

## 八、后续优化方向

1. **视频风格统一**：全局调色/滤镜，让不同来源的图片风格一致
2. **BGM 自动匹配**：复用现有 `determine_music_style()` + `download_random_bgm()` 逻辑
3. **多语言支持**：中英双语视频自动生成
4. **批量处理**：支持一次处理多篇文章
5. **封面自动生成**：从最终视频提取首帧作为封面（复用现有逻辑）
6. **交互优化**：增加进度反馈，长视频处理时显示进度条
7. **素材来源扩展**：除 Pexels 外，支持 Unsplash、Pixabay 等图片源
8. **Remotion 模板扩展**：增加更多动画模板，覆盖更多镜头类型
