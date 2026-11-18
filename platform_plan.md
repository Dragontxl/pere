# 图文+Remotion 自动视频生成系统 — 平台建设方案

> **基于**：`info.txt` 中的需求，结合 `F:\GO\videomodifyauto - 2.0V2` 项目可复用功能
> **目标**：将本地视频生成脚本升级为云端 Web 平台，用户通过网页发起任务、实时监控进度、管理下载产物

---

## 一、需求拆解

> **阶段进度**：
> - ✅ 阶段一：GitHub 仓库创建与脱敏推送（54 文件 → 96 文件）
> - ✅ 阶段二：后端 API 开发（Cloudflare Workers，20 文件）
> - ✅ 阶段三：GitHub Actions Workflow 改造 + main.py CI 集成
> - ✅ 阶段四：前端开发（React + Vite + TypeScript，18 文件）
> - ✅ 阶段五：部署与集成（Worker 已部署，D1/R2 已配置，前端已上线）
>
> **部署状态**：
> - Worker `pexel-remotion-worker` 已部署，自定义域名 `pere.ygtxl.dpdns.org` 已绑定
> - Worker 同时提供 API（`/api/*`）和前端静态资源（assets + SPA 路由）
> - D1 数据库 `pexel-remotion-db` 已创建并执行 schema 迁移（6 张表）
> - R2 桶 `pexel-remotion-bucket` 已创建
> - API 登录验证通过（admin / admin123）
> - 前端页面验证通过（https://pere.ygtxl.dpdns.org）
> - GitHub Actions Secrets 需用户手动配置（见 DEPLOYMENT.md）
> - R2 Access Keys 需用户在 Cloudflare Dashboard 手动创建

| 编号 | 需求 | 说明 |
|---|---|---|
| 1 | 代码上传 GitHub | 仓库公开，注意脱敏，使用 PAT 推送 |
| 2 | Web 使用平台 | 网页形式，密码登录，部署在 Cloudflare |
| 3 | 发起任务 | 大模型生成文稿 / 粘贴文稿 / 上传文稿，触发 GitHub Actions workflow |
| 4 | 实时监控 | workflow 运行进度在平台实时展示 |
| 5 | 产物管理 | 生成过程材料和最终视频保存到 Cloudflare R2，用户可管理及下载 |
| 6 | 复用参考项目功能 | 与 `videomodifyauto - 2.0V2` 使用同一个 CF 和 R2，复用其成熟功能 |

---

## 二、可从 videomodifyauto 项目复用的功能

经过对 `F:\GO\videomodifyauto - 2.0V2` 的代码分析，以下功能可直接复用或适配到本项目：

### 2.1 认证系统（直接复用）

| 组件 | 参考文件 | 复用方式 |
|---|---|---|
| 密码哈希与验证 | `backend/src/services/CryptoService.ts` 的 `hashPassword` / `verifyPassword` | **直接复制**，AES-GCM 加密 + SHA-256 加盐哈希 |
| JWT 令牌生成/验证 | `CryptoService.ts` 的 `generateToken` / `verifyToken` | **直接复制**，使用 jose 库，24h 过期 |
| 登录接口 | `backend/src/routes/public/auth.ts` | **直接复制**，`POST /api/v1/auth/login` |
| 刷新令牌 | `auth.ts` 的 `POST /refresh` | **直接复制** |
| 认证中间件 | `backend/src/middleware/auth.ts` | **直接复制**，保护需要登录的路由 |
| 用户表 | `schema.sql` 的 `users` 表 | **直接复用**，含 username/password_hash/role/api_key |

### 2.2 任务管理架构（适配复用）

参考项目采用 **阶段式任务模型**（DETECT → ANALYZE → CROP_SHOTS → CONVERT_FRAMES → GENERATE_SHOTS → COMPOSE），本项目适配为视频生成的 **阶段式模型**：

| 参考项目阶段 | 本项目对应阶段 | 说明 |
|---|---|---|
| DETECT | SCENE_GEN（分镜生成） | LLM 将文章拆解为镜头列表 |
| ANALYZE | ASSET_MATCH（素材匹配） | Pexels 图片下载 + CLIP 匹配 |
| CROP_SHOTS | REMOTION_RENDER（片段渲染） | Remotion 编码视频 + 图片 Ken Burns |
| CONVERT_FRAMES | TTS_COMPOSE（语音+合成） | TTS 合成 + 拼接 + 字幕 |

**复用的核心组件**：

| 组件 | 参考文件 | 复用方式 |
|---|---|---|
| TaskService 任务服务 | `backend/src/services/TaskService.ts` | **参考架构重写**，保留任务 CRUD、状态机、阶段推进逻辑 |
| 任务路由 | `backend/src/routes/public/tasks.ts` | **参考重写**，适配本项目的任务字段和阶段 |
| 任务状态机 | `TaskService.ts` 的 `advancePhase` / `triggerPhase` | **参考重写**，推进阶段状态 |
| 操作日志 | `schema.sql` 的 `operation_logs` 表 + `TaskService.getTaskLogs` | **直接复用**，记录每阶段日志 |
| 任务过期清理 | `scheduled.ts` 的 `cleanupExpiredTasks` | **直接复制** |

### 2.3 GitHub Actions 触发机制（适配复用）

参考项目通过 `repository_dispatch` API 触发 workflow，这是本项目的核心触发方式。

**复用的核心组件**：

| 组件 | 参考文件 | 复用方式 |
|---|---|---|
| workflow 触发函数 | `TaskService.ts` 的 `dispatchGitHubWorkflow` | **参考重写**，POST `api.github.com/repos/{owner}/{repo}/dispatches`，传入 `event_type` + `client_payload` |
| 回调处理 | `backend/src/routes/public/callback.ts` | **参考重写**，workflow 完成后回调更新任务状态 |
| 回调路由 | `callbackRoutes` 的 `/github` `/progress` `/complete` `/error` | **参考重写**，适配本项目的阶段 |
| 回调签名验证 | `CryptoService.ts` 的 `generateHMAC` / `verifyHMAC` | **直接复制**，HMAC-SHA256 验证回调来源 |
| workflow 末尾通知 | `video-processing.yml` 的 "Notify completion" 步骤 | **参考重写**，curl POST 回调后端 |

### 2.4 R2 文件管理（直接复用）

参考项目的 R2 文件管理功能非常成熟，本项目直接复用。

**复用的核心组件**：

| 组件 | 参考文件 | 复用方式 |
|---|---|---|
| 文件预览 | `backend/src/routes/public/files.ts` 的 `/preview/:filename` | **直接复制**，支持 Range 请求、视频流式播放 |
| 文件版本检查 | `files.ts` 的 `/version/:filename` | **直接复制**，返回 ETag/Last-Modified |
| 无缓存访问 | `files.ts` 的 `/nocache/*` | **直接复制** |
| 缓存刷新 | `files.ts` 的 `/purge` | **直接复制**，调用 Cloudflare API 刷新缓存 |
| 文件上传 | `backend/src/routes/admin/files.ts` | **直接复制**，支持分片上传（uploads/upload_parts 表） |
| 文件浏览器前端 | `frontend/src/pages/FileBrowser.tsx` | **直接复制**，复用 R2 目录浏览、选择、下载 UI |

### 2.5 前端框架（适配复用）

参考项目前端为 React + Ant Design，部署在 Cloudflare Pages。

**复用的核心组件**：

| 组件 | 参考文件 | 复用方式 |
|---|---|---|
| 登录页 | `frontend/src/pages/Login.tsx` | **直接复制** |
| 受保护路由 | `frontend/src/components/ProtectedRoute.tsx` | **直接复制** |
| 布局组件 | `frontend/src/components/Layout.tsx` | **直接复制** |
| API 封装 | `frontend/src/api/index.ts` | **参考重写**，适配本项目接口 |
| 任务列表页 | `frontend/src/pages/Tasks.tsx` | **参考重写**，适配本项目任务字段（文章内容、阶段状态） |
| 任务详情页 | `frontend/src/pages/TaskDetail.tsx` | **参考重写**，进度 Timeline + 阶段控制 + 产物下载 |
| 视频播放器 | `frontend/src/components/VideoPlayer.tsx` | **直接复制** |
| 部署工作流 | `.github/workflows/deploy-frontend.yml` | **直接复制**，适配项目名 |

### 2.6 Cloudflare 配置（直接复用）

| 配置项 | 参考文件 | 复用方式 |
|---|---|---|
| wrangler.toml | `backend/wrangler.toml` | **参考复制**，复用 D1/R2/KV binding、cron 触发器 |
| 前端部署 | `frontend` 的 Vite + Pages | **直接复制**构建配置 |

---

## 三、总体架构设计

### 3.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户浏览器                                │
│  登录 → 发起任务 → 实时查看进度 → 下载最终视频                     │
└──────────────┬──────────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────────┐
│              Cloudflare Pages（前端静态站点）                     │
│  React + Ant Design，密码登录，任务管理 UI                        │
└──────────────┬──────────────────────────────────────────────────┘
               │ HTTPS API
┌──────────────▼──────────────────────────────────────────────────┐
│           Cloudflare Workers（后端 API）                         │
│  Hono 框架，JWT 认证，D1 数据库，R2 存储绑定                      │
│                                                                  │
│  ┌───────────┐  ┌─────────────┐  ┌──────────────┐               │
│  │ 认证模块   │  │ 任务管理模块  │  │ 文件管理模块   │               │
│  │ login     │  │ CRUD + 阶段  │  │ R2 预览/下载  │               │
│  │ JWT中间件 │  │ 状态机推进   │  │ 上传/删除     │               │
│  └───────────┘  └──────┬──────┘  └──────────────┘               │
│                         │                                        │
│                    repository_dispatch                          │
│                    （GitHub API 触发）                            │
└────────────────────────┼─────────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────────┐
│              GitHub Actions（视频生成 Workflow）                  │
│                                                                  │
│  用户发起任务 → 后端 dispatch → workflow 运行                     │
│                                                                  │
│  阶段1: SCENE_GEN       LLM 分镜生成 → scenes.json               │
│  阶段2: ASSET_MATCH     Pexels 下载 + CLIP 匹配 → match_results  │
│  阶段3: REMOTION_RENDER Remotion 渲染 + Ken Burns → clips        │
│  阶段4: TTS_COMPOSE     TTS + 拼接 + 字幕 → final_output.mp4    │
│                                                                  │
│  各阶段产物上传 R2，进度回调后端，完成回调通知                     │
└──────────────────────────────────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────────┐
│              Cloudflare R2（对象存储）                            │
│  任务产物：分镜数据 / 候选图片 / 视频片段 / 最终视频              │
│  公开域名直接访问，支持 Range 流式播放                            │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 任务状态机

参考项目的阶段式状态机，本项目适配为：

```
PENDING（等待中）
  └─→ SCENE_GEN_PENDING（分镜生成等待）
        └─→ SCENE_GEN_ING（分镜生成中）
              └─→ SCENE_GEN_DONE（分镜完成）
                    └─→ ASSET_MATCH_PENDING（素材匹配等待）
                          └─→ ASSET_MATCH_ING（素材匹配中）
                                └─→ ASSET_MATCH_DONE（匹配完成）
                                      └─→ REMOTION_RENDER_PENDING（渲染等待）
                                            └─→ REMOTION_RENDER_ING（渲染中）
                                                  └─→ REMOTION_RENDER_DONE（渲染完成）
                                                        └─→ TTS_COMPOSE_PENDING（合成等待）
                                                              └─→ TTS_COMPOSE_ING（合成中）
                                                                    └─→ COMPLETED（已完成）
                                                                            
异常分支：任一阶段失败 → FAILED；用户操作 → CANCELLED
```

### 3.3 数据流时序

```
用户                前端                后端 API              GitHub Actions         R2
│                    │                    │                     │                  │
│ 输入文章并点击提交  │                    │                     │                  │
│──────────────────→│                    │                     │                  │
│                    │ POST /api/v1/tasks │                     │                  │
│                    │──────────────────→│ 创建任务(PENDING)    │                  │
│                    │                    │ 触发 workflow        │                  │
│                    │                    │── repository_dispatch─────────────→│
│                    │                    │                     │ 开始运行         │
│                    │                    │←── progress callback ─│                  │
│                    │←── 轮询任务详情 ────│ 更新进度            │                  │
│                    │   (每5-10秒)      │                     │                  │
│                    │                    │                     │ 上传中间产物 ──→│
│                    │                    │                     │ (分镜/图片/片段)   │
│                    │                    │←── progress callback ─│                  │
│                    │←── 轮询任务详情 ────│ 更新进度            │                  │
│                    │                    │                     │                  │
│                    │                    │                     │ 上传最终视频 ──→│
│                    │                    │←── complete callback ─│                  │
│                    │                    │ 更新为 COMPLETED     │                  │
│                    │←── 轮询任务详情 ────│                     │                  │
│                    │                     │                     │                  │
│ 下载最终视频        │ GET 文件预览        │                     │                  │
│──────────────────→│──────────────────→│ 代理 R2 返回视频流    │                  │
│                    │                    │←───────────────────────────────────────│
│←── 视频流 ─────────│←── 视频流 ─────────│                     │                  │
```

---

## 四、详细实施计划

### 阶段一：GitHub 仓库准备与脱敏

**目标**：将代码推送到公开 GitHub 仓库，确保无敏感信息泄露。

#### 4.1.1 仓库创建与脱敏检查

1. **创建公开仓库**：使用 GitHub CLI 创建公开仓库（PAT 通过环境变量传入，不写入仓库）
   ```bash
   gh repo create pere --public --description "图文+Remotion 自动视频生成系统"
   ```

2. **脱敏检查清单**：
   - `config/settings.json`：**必须移除**所有 API Key、密钥、路径等敏感配置
   - `.gitignore`：确保排除 `temp/`、`assets/`（运行产物）、`node_modules/`、`__pycache__/`
   - 代码中硬编码的密钥：全局搜索 `api_key`、`secret`、`token`、`password` 等，确认无硬编码
   - `test_*.py` 测试文件中的密钥：检查并移除
   - `README.md`：确认无敏感信息

3. **配置管理**：敏感配置通过 GitHub Actions Secrets 和 Cloudflare Workers 环境变量管理，不进仓库

#### 4.1.2 代码推送

```bash
git init
git add .
git commit -m "initial: 图文+Remotion 自动视频生成系统"
git branch -M main
git remote add origin https://github.com/<user>/pere.git
git push -u origin main
```

#### 4.1.3 GitHub Secrets 配置

在仓库 Settings → Secrets 中配置以下 Secrets：
- `ZHIPU_API_KEY` — 智谱 AI API Key
- `AGNES_API_KEY` / `AGNES_BASE_URL` — Agnes 模型 API
- `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_ENDPOINT_URL` / `R2_BUCKET_NAME` — R2 访问凭证
- `CALLBACK_URL` / `CALLBACK_SECRET` — 回调地址与签名密钥
- `GITHUB_PAT` — 触发 workflow 的 PAT（若用 PAT 而非 GITHUB_TOKEN）

---

### 阶段二：后端 API 开发（Cloudflare Workers）

**目标**：基于 videomodifyauto 的后端架构，搭建本项目的 API 服务。

#### 4.2.1 项目结构

```
pexel-remotion/
├── backend/                    # Cloudflare Workers 后端
│   ├── src/
│   │   ├── index.ts            # Hono 应用入口，路由注册
│   │   ├── scheduled.ts        # Cron 定时任务（过期清理、任务调度）
│   │   ├── types/
│   │   │   ├── env.ts          # Bindings 类型定义
│   │   │   └── index.ts        # 类型定义
│   │   ├── middleware/
│   │   │   ├── auth.ts         # JWT 认证中间件（复用）
│   │   │   ├── error.ts        # 错误处理中间件（复用）
│   │   │   └── logger.ts       # 日志中间件（复用）
│   │   ├── services/
│   │   │   ├── CryptoService.ts     # 加密/JWT/HMAC（直接复用）
│   │   │   ├── TaskService.ts       # 任务服务（参考重写）
│   │   │   ├── ConfigService.ts     # 配置服务（复用）
│   │   │   └── ErrorHandlerService.ts # 错误处理（复用）
│   │   ├── routes/
│   │   │   ├── public/
│   │   │   │   ├── auth.ts     # 登录/刷新（直接复用）
│   │   │   │   ├── tasks.ts    # 任务 CRUD（参考重写）
│   │   │   │   ├── callback.ts # GitHub 回调（参考重写）
│   │   │   │   └── files.ts    # R2 文件访问（直接复用）
│   │   │   └── admin/
│   │   │       ├── tasks.ts    # 管理端任务操作（参考重写）
│   │   │       ├── files.ts    # 文件上传/删除（直接复用）
│   │   │       └── config.ts   # 系统配置（复用）
│   │   └── database/
│   │       └── schema.sql      # D1 数据库 schema（参考重写）
│   ├── wrangler.toml           # Worker 配置（参考复制）
│   ├── wrangler.toml.example   # 配置模板
│   ├── package.json
│   ├── tsconfig.json
│   └── .env.example
```

#### 4.2.2 数据库 Schema（适配本项目）

参考 videomodifyauto 的 schema，精简为本项目所需的表：

```sql
-- 用户表（直接复用）
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    role TEXT DEFAULT 'USER',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    api_key TEXT UNIQUE
);

-- 任务表（适配本项目字段）
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    article_source TEXT NOT NULL,  -- 'ai_generated' | 'pasted' | 'uploaded'
    article_content TEXT,          -- 文章原文（粘贴/AI生成时存入）
    article_file_key TEXT,         -- 上传文件在 R2 中的 key
    status TEXT NOT NULL DEFAULT 'PENDING',
    current_phase TEXT,
    -- 阶段产物路径（R2 key）
    scenes_key TEXT,               -- 分镜数据
    match_results_key TEXT,        -- 素材匹配结果
    final_video_key TEXT,          -- 最终视频
    final_video_url TEXT,          -- 最终视频公开 URL
    progress INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    error_msg TEXT,
    status_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    expires_at TIMESTAMP
);

-- 操作日志表（直接复用）
CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT,
    phase TEXT,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 系统配置表（直接复用）
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT
);
```

#### 4.2.3 任务 API 设计

| 方法 | 路径 | 说明 | 认证 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | 登录获取 JWT | 否 |
| POST | `/api/v1/auth/refresh` | 刷新令牌 | 是 |
| GET | `/api/v1/tasks` | 任务列表（分页、状态筛选） | 是 |
| GET | `/api/v1/tasks/:id` | 任务详情（含进度） | 是 |
| POST | `/api/v1/tasks` | 创建任务（发起视频生成） | 是 |
| PUT | `/api/v1/tasks/:id` | 更新任务 | 是 |
| DELETE | `/api/v1/tasks/:id` | 删除任务（连带清理 R2 文件） | 是 |
| POST | `/api/v1/tasks/:id/cancel` | 取消任务 | 是 |
| POST | `/api/v1/tasks/:id/retry` | 重试失败任务 | 是 |
| POST | `/api/v1/callback/github` | GitHub workflow 回调 | HMAC签名 |
| POST | `/api/v1/callback/progress` | 进度回调 | HMAC签名 |
| POST | `/api/v1/callback/complete` | 完成回调 | HMAC签名 |
| POST | `/api/v1/callback/error` | 错误回调 | HMAC签名 |
| GET | `/api/v1/files/preview/:filename` | R2 文件预览/播放 | 否（或公开） |
| POST | `/api/v1/admin/files/upload` | 文件上传（文章上传） | 是 |
| POST | `/api/v1/admin/files/delete` | 文件删除 | 是 |

#### 4.2.4 创建任务流程（核心）

用户通过前端发起任务时，后端处理逻辑：

```
1. 接收请求：article_source + article_content（或 article_file_key）
2. 生成 task_id（UUID）
3. 写入 tasks 表（status=PENDING, current_phase=null）
4. 组装 client_payload：
   {
     "task_id": "uuid",
     "article_source": "ai_generated | pasted | uploaded",
     "article_content": "文章文本（AI生成或粘贴时直接传入）",
     "article_file_key": "R2中的文章文件key（上传时）",
     "orientation": "landscape | portrait",
     "language": "zh | en",
     "enable_subtitle": true,
   }
5. 调用 GitHub API：POST /repos/{owner}/{repo}/dispatches
   event_type: "video-generation"
   client_payload: 上述 payload
6. 返回 task_id 给前端
7. 前端轮询任务详情，后端从回调更新进度
```

#### 4.2.5 回调处理逻辑

GitHub Actions workflow 各阶段完成时回调后端：

| 回调接口 | 触发时机 | 处理逻辑 |
|---|---|---|
| `/callback/github` | workflow 整体完成/失败 | 验证 HMAC 签名 → 根据 status 更新任务为 COMPLETED 或 FAILED → 记录日志 |
| `/callback/progress` | 各阶段完成 | 验证签名 → 更新 current_phase 和 progress → 记录日志 → 触发 advancePhase |
| `/callback/complete` | 最终视频生成完成 | 验证签名 → 获取最终视频 R2 key → 更新 final_video_key / final_video_url → 标记 COMPLETED |
| `/callback/error` | 阶段异常 | 验证签名 → 更新 error_msg → 标记 FAILED |

**阶段推进逻辑**（参考 `advancePhase`）：

```
current_phase = task.current_phase
阶段顺序：SCENE_GEN → ASSET_MATCH → REMOTION_RENDER → TTS_COMPOSE
若当前阶段完成：
  1. 查找下一个阶段
  2. 更新 current_phase 为下一阶段
  3. 更新 status 为下一阶段的 _ING 状态
  4. 再次 dispatch workflow（event_type=video-generation，payload 含 start_phase/end_phase）
若已是最后阶段：标记 COMPLETED
```

#### 4.2.6 Cron 定时任务

参考 `scheduled.ts`，配置：

| Cron | 任务 |
|---|---|
| `*/5 * * * *` | 扫描 PENDING 任务并自动启动（若用户未手动触发） |
| `*/30 * * * *` | 清理过期任务及关联的 R2 文件 |
| `0 0 * * *` | 重置每日统计 |

---

### 阶段三：GitHub Actions Workflow 改造

**目标**：将现有 `video-generation.yml` 改造为支持远程触发、分阶段执行、回调通知的完整工作流。

#### 4.3.1 Workflow 触发方式改造

现有 workflow 仅支持 `workflow_dispatch`（手动触发），需改造为同时支持 `repository_dispatch`：

```yaml
name: 视频生成

on:
  repository_dispatch:
    types: [video-generation]
  workflow_dispatch:
    inputs:
      article_content:
        description: '文章内容'
        required: true
        type: string

jobs:
  generate-video:
    runs-on: ubuntu-latest
    timeout-minutes: 360
    concurrency:
      group: ${{ github.event.client_payload.task_id }}
      cancel-in-progress: false
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          cd remotion && npm install
      - name: Setup ffmpeg
        run: sudo apt-get update && sudo apt-get install -y ffmpeg
      - name: Generate video
        env:
          TASK_ID: ${{ github.event.client_payload.task_id }}
          ARTICLE_SOURCE: ${{ github.event.client_payload.article_source }}
          ARTICLE_CONTENT: ${{ github.event.client_payload.article_content }}
          ARTICLE_FILE_KEY: ${{ github.event.client_payload.article_file_key }}
          ORIENTATION: ${{ github.event.client_payload.orientation || 'landscape' }}
          LANGUAGE: ${{ github.event.client_payload.language || 'zh' }}
          ZHIPU_API_KEY: ${{ secrets.ZHIPU_API_KEY }}
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
          R2_ENDPOINT_URL: ${{ secrets.R2_ENDPOINT_URL }}
          R2_BUCKET_NAME: ${{ secrets.R2_BUCKET_NAME }}
          CALLBACK_URL: ${{ secrets.CALLBACK_URL }}
          CALLBACK_SECRET: ${{ secrets.CALLBACK_SECRET }}
        run: |
          python main.py --task-id "$TASK_ID" \
            --article-source "$ARTICLE_SOURCE" \
            --article-file-key "$ARTICLE_FILE_KEY" \
            --orientation "$ORIENTATION" \
            --language "$LANGUAGE" \
            --output-dir ./output
      - name: Upload to R2
        run: |
          # 使用 rclone 或 wrangler 上传 output/ 下所有产物到 R2
          # key 格式: {task_id}/{产物路径}
          wrangler r2 object create "r2://$R2_BUCKET_NAME/$TASK_ID/final_output.mp4" ./output/final_output.mp4
          wrangler r2 object create "r2://$R2_BUCKET_NAME/$TASK_ID/scenes.json" ./output/scenes.json
          # ... 其他产物
      - name: Notify completion
        if: always()
        run: |
          STATUS="${{ job.status }}"
          # 回调后端，通知任务完成/失败
          curl -s -X POST "$CALLBACK_URL/github" \
            -H "Content-Type: application/json" \
            -H "X-Callback-Signature: $CALLBACK_SECRET" \
            -d "{
              \"task_id\": \"$TASK_ID\",
              \"status\": \"$STATUS\",
              \"run_id\": \"${{ github.run_id }}\"
            }"
```

#### 4.3.2 main.py 改造要点

在现有 `main.py` 基础上增加 CI 适配：

1. **新增 `--task-id` 参数**：传入任务 ID，用于产物命名和 R2 路径
2. **新增 `--article-source` 参数**：区分文章来源（ai_generated/pasted/uploaded）
3. **新增 `--article-file-key` 参数**：上传文章的 R2 key，workflow 中从 R2 下载文章文件
4. **阶段产物上传 R2**：每个阶段完成后，将中间产物上传到 R2（scenes.json、match_results.json、final_output.mp4 等）
5. **阶段进度回调**：每个阶段开始/完成时，POST 回调后端更新进度
6. **R2 上传脚本**：使用 `wrangler` CLI 或 AWS SDK 上传产物到 R2

#### 4.3.3 产物 R2 路径规范

```
{task_id}/
├── scenes.json              # 分镜数据
├── match_results.json       # 素材匹配结果
├── decisions.json           # 综合决策结果
├── clips/                   # 视频片段（Remotion 渲染 + Ken Burns）
│   ├── clip_1.mp4
│   ├── clip_2.mp4
│   └── ...
├── final_output.mp4         # 最终视频
└── logs.txt                 # 运行日志
```

---

### 阶段四：前端开发（Cloudflare Pages）

**目标**：构建用户使用平台网页，复用 videomodifyauto 前端框架。

#### 4.4.1 前端页面设计

| 页面 | 路由 | 功能 | 参考来源 |
|---|---|---|---|
| 登录页 | `/login` | 用户名密码登录 | 直接复用 Login.tsx |
| 任务列表 | `/tasks` | 展示用户所有任务，筛选状态，新建任务 | 参考重写 Tasks.tsx |
| 任务详情 | `/tasks/:id` | 进度时间线、阶段控制、产物预览/下载 | 参考重写 TaskDetail.tsx |
| 文件管理 | `/files` | R2 文件浏览、下载 | 直接复用 FileBrowser.tsx |
| 个人中心 | `/profile` | 用户信息、API Key 管理 | 参考 Accounts.tsx 简化 |

#### 4.4.2 任务列表页适配

参考 videomodifyauto 的 Tasks.tsx，适配本项目任务字段：

- **状态展示**：PENDING / SCENE_GEN_ING / ASSET_MATCH_ING / REMOTION_RENDER_ING / TTS_COMPOSE_ING / COMPLETED / FAILED / CANCELLED
- **创建任务弹窗**：
  - 任务标题（可选）
  - 文章来源选择：智能体生成（输入话题）/ 粘贴文稿（文本框）/ 上传文稿（文件上传到 R2）
  - 图片方向：横屏 / 竖屏
  - 语言：中文 / 英文
  - 是否添加字幕：是/否
- **操作按钮**：查看详情、取消、重试、删除

#### 4.4.3 任务详情页适配

参考 videomodifyauto 的 TaskDetail.tsx，适配本项目：

- **基本信息卡片**：任务ID、状态、文章来源、当前阶段、进度条
- **进度时间线**：4 个阶段（分镜生成 → 素材匹配 → 片段渲染 → 语音合成），实时刷新
- **阶段状态展示**：每个阶段显示状态（等待/进行中/完成/失败）
- **产物区域**：
  - 最终视频：内嵌视频播放器（通过 R2 公开 URL + Range 请求）
  - 分镜数据：可查看 scenes.json（格式化展示）
  - 素材匹配结果：展示选中的图片缩略图
  - 下载按钮：下载最终视频、下载分镜数据
- **操作日志**：展示 operation_logs 记录

#### 4.4.4 实时监控实现

参考 videomodifyauto 的轮询方案：

- 任务详情页每 5-10 秒轮询 `GET /api/v1/tasks/:id` 获取最新状态
- 前端对比前后两次状态，变化时更新 UI
- 进度条根据 `progress` 字段更新
- 使用 `requestAnimationFrame` 或 `setInterval` 实现平滑刷新

---

### 阶段五：部署与联调

#### 4.5.1 Cloudflare 资源准备

本项目与 videomodifyauto 使用**同一个 Cloudflare 账户**，但使用**独立的资源**（Worker、Pages、D1、R2 桶各自独立）：

**CF 账户信息**（已通过 API 确认）：

| 项目 | 值 |
|---|---|
| 账户名称 | `Goodluckjiachen@foxmail.com's Account` |
| 账户 ID | `d30bed2763a23cf8eddf343ca192c5ff` |
| 根域名 | `ygtxl.dpdns.org`（Zone ID: `a591cd553ec34768475ee2010d4cd7ab`） |
| 辅助域名 | `luckydragon.us.ci`（Zone ID: `22e37afab3d185c7c071505b6588690a`） |

**资源对照表**：

| 资源 | 参考项目 | 本项目 | 说明 |
|---|---|---|---|
| Worker | `ai-video-worker` | `pexel-remotion-worker` | 独立 Worker，同一 CF 账户 |
| D1 数据库 | `ai-video-db` | `pexel-remotion-db` | 独立数据库（新建 D1） |
| R2 存储桶 | `ai-video-bucket` | `pexel-remotion-bucket` | 在 CF 上新建独立 R2 桶，桶内用 `{task_id}/` 前缀隔离各任务产物 |
| Pages 项目 | `ai-video-frontend` | `pexel-remotion-frontend` | 独立 Pages 项目 |
| KV | `KV` | 复用或新建 | 按需 |
| 自定义根域名 | `ygtxl.dpdns.org` | `ygtxl.dpdns.org`（同一个根域名） | 两个项目共用同一个根域名，本项目前端使用子域名 `pere.ygtxl.dpdns.org` |

> **R2 方案说明**：本项目在 CF 上**新建独立的 R2 桶**（`pexel-remotion-bucket`），与 videomodifyauto 的 `ai-video-bucket` 互不共用。桶内以 `{task_id}/` 前缀隔离各任务的产物。R2 桶绑定与根域名相同的自定义域名，最终视频通过该域名直接流式播放。

#### 4.5.2 部署步骤

1. **后端部署**：
   ```bash
   cd backend
   npm install
   # 配置 wrangler.toml，使用 CF API Token
   npx wrangler deploy
   # 初始化 D1 数据库
   npx wrangler d1 execute pexel-remotion-db --file=./src/database/schema.sql
   ```

2. **前端部署**：
   ```bash
   cd frontend
   npm install
   npm run build
   # 通过 Cloudflare Pages 部署，或使用 deploy-frontend.yml 自动部署
   # 部署后在 Pages 项目设置中绑定自定义域名：pere.ygtxl.dpdns.org
   ```

3. **GitHub Actions 部署工作流**：
   - 参考 `deploy-frontend.yml`，push 到 main 时自动部署前端
   - 后端可通过手动部署或 CI 部署

#### 4.5.3 环境变量配置

后端 `wrangler.toml` 需配置的环境变量（通过 CF Dashboard → Workers → Settings → Variables 配置）：

```
JWT_SECRET          # JWT 签名密钥（随机字符串）
ENCRYPTION_KEY      # AES 加密密钥（至少32字节）
ADMIN_API_KEY       # 管理端 API 密钥
CALLBACK_SECRET     # 回调 HMAC 签名密钥
ENVIRONMENT         # production
GITHUB_REPO_OWNER   # 仓库 owner
GITHUB_REPO_NAME    # pere
FRONTEND_URL        # https://pere.ygtxl.dpdns.org
R2_PUBLIC_URL       # https://pexel-remotion-bucket.<R2公开域名>（新建桶后配置）
CLOUDFLARE_ZONE_ID  # a591cd553ec34768475ee2010d4cd7ab（ygtxl.dpdns.org）
```

GitHub Actions Secrets 需配置：
```
ZHIPU_API_KEY       # 智谱 AI
AGNES_API_KEY       # Agnes 模型
R2_ACCESS_KEY_ID    # R2 访问
R2_SECRET_ACCESS_KEY
R2_ENDPOINT_URL
R2_BUCKET_NAME
CALLBACK_URL        # 后端回调地址
CALLBACK_SECRET
```

---

## 五、项目结构总览

```
pexel-remotion/                          # 本地目录（GitHub 仓库名：pere）
│
├── README.md                           # 项目说明
├── requirements.txt                    # Python 依赖
├── main.py                             # 视频生成主流程（改造为 CI 模式）
│
├── core/                               # Python 核心模块（保持现有）
│   ├── article_input.py
│   ├── scene_generator.py
│   ├── asset_matcher/
│   ├── remotion_analyzer.py
│   ├── decision_engine.py
│   └── composer/
│
├── remotion/                           # Remotion 渲染（保持现有）
│   ├── templates/
│   ├── render.js
│   └── Root.js
│
├── config/
│   ├── settings.json                   # 配置（脱敏，不含密钥）
│   └── render_params.json
│
├── .github/
│   └── workflows/
│       ├── video-generation.yml        # 视频生成 workflow（改造）
│       └── deploy-frontend.yml         # 前端部署 workflow（新增）
│
├── backend/                            # 新增：Cloudflare Workers 后端
│   ├── src/
│   │   ├── index.ts
│   │   ├── scheduled.ts
│   │   ├── types/
│   │   ├── middleware/
│   │   ├── services/
│   │   ├── routes/
│   │   │   ├── public/
│   │   │   └── admin/
│   │   └── database/
│   │       └── schema.sql
│   ├── wrangler.toml
│   ├── wrangler.toml.example
│   ├── package.json
│   └── tsconfig.json
│
├── frontend/                           # 新增：React 前端
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── public/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── assets/                             # 运行产物（本地调试用，不推送）
├── temp/                               # 临时文件（不推送）
└── platform_plan.md                    # 本方案文档
```

---

## 六、风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 公开仓库泄露密钥 | 安全风险 | 提交前全局搜索敏感信息；API Key 全部走 Secrets/环境变量；`.gitignore` 排除产物目录 |
| PAT 过期或权限不足 | 推送失败、触发 workflow 失败 | 使用 scope 最小化的 PAT；定期检查有效期；准备备用 PAT |
| GitHub Actions 运行时间长被截断 | 视频生成超时 | 设置合理 `timeout-minutes`（360）；分阶段执行，单阶段超时不影响其他任务；concurrency 控制并发 |
| workflow 回调丢失 | 任务状态不更新 | 回调加入重试机制（参考 videomodifyauto 的 3 次重试）；前端轮询兜底，状态不一致时可手动刷新 |
| R2 大文件上传超时 | 产物上传失败 | 使用 `wrangler r2` 或分片上传；最终视频较大时考虑异步上传 |
| Cloudflare Workers CPU 时间限制 | 后端处理超时 | 后端仅做轻量任务管理（CRUD + 回调处理），重活全部在 GitHub Actions |
| D1 查询限制 | 任务列表卡顿 | 合理建索引（status、user_id、created_at）；分页查询 |
| 多用户并发任务 | workflow 排队拥堵 | 使用 `concurrency` 限制并发任务数；配置 `max_concurrent_tasks` 系统配置 |
| Remotion 渲染在 CI 环境失败 | 视频生成中断 | 代码模板化 + 语法检查；渲染失败时回退到图片方案（已有兜底逻辑） |

---

## 七、里程碑与时间规划

| 阶段 | 内容 | 预估周期 |
|---|---|---|
| **阶段一** | GitHub 仓库创建、代码脱敏、推送 | 1 天 |
| **阶段二** | 后端 API 开发（认证、任务、回调、文件） | 3-4 天 |
| **阶段三** | Workflow 改造（远程触发、分阶段、回调、R2 上传） | 2-3 天 |
| **阶段四** | 前端开发（登录、任务列表、任务详情、文件管理） | 3-4 天 |
| **阶段五** | 部署联调、端到端测试 | 2 天 |

**总计预估**：11-14 天

---

## 八、验收标准

1. **代码安全**：公开仓库中无 API Key、密钥、密码等敏感信息
2. **平台可用**：用户可通过网页登录，密码验证通过
3. **任务发起**：三种文章输入方式（AI 生成、粘贴、上传）均可创建任务并触发 workflow
4. **进度监控**：任务详情页实时展示 4 个阶段的进度，状态变化在 10 秒内更新
5. **产物管理**：最终视频和过程材料保存在 R2，用户可在线预览和下载
6. **回调闭环**：workflow 完成/失败均能正确回调后端，任务状态准确更新
7. **端到端**：从用户发起任务到最终视频生成下载，全流程无人工干预自动完成

---

## 九、后续优化方向

1. **定时任务**：用户可设定定时生成（参考 videomodifyauto 的 `scheduled_at` 字段）
2. **任务重试**：失败任务一键重试，自动重新触发 workflow
3. **批量处理**：支持一次提交多篇文章批量生成
4. **素材预览**：任务详情页展示匹配的图片素材缩略图
5. **Webhook 替代轮询**：使用 Server-Sent Events 或 WebSocket 实现更实时的进度推送
6. **用户配额**：限制每用户每日任务数，防止滥用
7. **封面自动生成**：从最终视频提取首帧作为任务封面
8. **BGM 支持**：用户可选择 4 段预设背景音乐或上传自定义音频文件，workflow 中混合。自定义 BGM 存储在 R2（key 以 `bgm/` 前缀区分），workflow 检测到该前缀时从 R2 下载到本地再传给 `main.py`。上传接口使用 JSON + base64 传输，因 Cloudflare Workers 环境下 multipart/form-data 的 Content-Type 会在边缘被剥离，`c.req.formData()` 不可用。

---

## 十、部署排障记录（2026-11-17 ~ 2026-11-18）

联调过程中踩到的问题与结论，后续改配置时对照检查：

| 问题 | 现象 | 结论 |
|---|---|---|
| `wrangler.toml` 里的 `${VAR}` | Worker 绑定值就是字面量 `${GITHUB_PAT}`，dispatch / JWT 全部失效 | wrangler 不做插值，密钥必须用 `wrangler secret put` 上传 |
| 前端点击任务卡片跳登录页 | `window.location.href` 整页刷新，`AuthContext` 在 `useEffect` 里恢复 token，首帧被判未登录 | token 改为 `useState` 惰性同步初始化，跳转改用 `useNavigate()` |
| 任务 ID 含中文 | `id` 取标题前 8 字符，中文任务无法用 URL 访问 | 改为 ASCII slug（非 ASCII 标题回退为 `task`）+ `crypto.randomUUID()` 片段 |
| workflow 参数全为空 | 用了不存在的 `$env:GITHUB_EVENT` | 改为读取 `$env:GITHUB_EVENT_PATH` 指向的 JSON |
| `& $cmd` 报「不是 cmdlet」 | PowerShell 把整个数组当成命令名 | `& $exe @cmdArgs` 展开传参 |
| R2 secrets 写进 PowerShell 数组 | 未加引号导致 ParserError | 通过 step `env` 传参，脚本里用 `$env:XXX` |
| deploy-backend 一直失败 | D1 迁移步骤没有 `CLOUDFLARE_API_TOKEN`；wrangler 4 要求 Node ≥ 22.12 | 迁移步骤补 token，三个 workflow 的 Node 统一为 22 |
| `npm install` peer 冲突 | wrangler 4 peer 要求 `@cloudflare/workers-types@^5` | devDependency 升到 `^5.20261117.1` |
| 任务跑成功但被标记 FAILED | `main.py` 向 `/callback/github` 发 `started` / `processing` / `completed`，旧 handler 只认 `status === 'success'`，进度回调全被判失败 | 回调做状态归一化：`started/processing/completed` 视为实时状态，`failed/error` 才算失败，且不回退终态任务 |
| 阶段回调不区分「阶段进度」与「整段完成」 | workflow 进度回调没有 `start_phase/end_phase`，handler 无法区分，导致阶段一完成就触发下一阶段、阶段产物缺失 | 带 `start_phase/end_phase` 的是整段事件（走完成/推进逻辑），不带的只是 `main.py` 阶段进度（只更新进度/状态标签，不触发新 run） |
| 单阶段串行不可行 | 图片素材只存在于当次 runner，换一次 checkout 后阶段 2/3 无素材可读 | 一次 GitHub run 跑完整管线 `SCENE_GEN → TTS_COMPOSE`，阶段进度由回调上报 |
| 进度条末阶段显示「进行中」 | `ProgressBar` 在 `progress=100` 时把最后一个阶段判为 current，`isCurrent` 分支优先输出「进行中」 | `isCompleted` 时不再输出「进行中」，改输出「已完成」 |
| 最终视频无法下载（404，key 为空） | `/files/nocache/*` 用路径通配符 `c.req.param('*')` 取 key，含斜杠的多段 key（`tasks/<id>/final_output.mp4`）在边缘运行时取到空串，`R2.get('')` 返回 404 | key 改从 query 参数 `?key=` 读取（与 `/version` 一致），并补上 Range 分片支持，视频预览/拖动/下载均可用 |
| dispatch 报 422「No more than 10 properties」 | 加 `bgm_key` 后 `client_payload` 达到 11 个属性，超过 GitHub repository_dispatch 上限 | 移除冗余的 `phase` 字段（与 `start_phase` 值相同且 workflow 不使用），保持 10 个以内 |
| runner 上 ffmpeg 找不到，`[WinError 2]` | `windows-latest` runner 无预装 ffmpeg，`_resolve_ffmpeg` 回退到 `"ffmpeg"` 字符串后 `subprocess` 抛 `FileNotFoundError`，字幕烧录/静音音轨/BGM 混合全失败 | workflow 用 `imageio-ffmpeg`（随 moviepy 安装）的 `get_ffmpeg_exe()` 设置 `IMAGEIO_FFMPEG_EXE` 环境变量，`_resolve_ffmpeg` 优先读取 |
| 带 BGM 的最终视频没上传到 R2 | `mix_bgm` 后 `main.py` 将 `final_output.mp4` 重命名为 `final_with_bgm.mp4`，原上传步骤只找 `final_output.mp4`，文件不存在被跳过 | 上传步骤检测两个文件，统一以 `final_output.mp4` 作为 R2 key，保证下载链接一致 |
| 自定义 BGM 上传返回 500「Content-Type header is missing」 | Cloudflare Workers 边缘会剥离 multipart/form-data 请求的 Content-Type，body 被消费为空（`content-length: 0`），`c.req.formData()` 不可用 | 改用 JSON + base64 传输：前端读取文件为 base64，后端 `c.req.json()` 解析后解码存入 R2，完全绕过 multipart 限制 |

当前状态：Worker / D1 / R2 / GitHub Actions 均已打通，创建任务即自动触发 `video-generation` workflow，一次 run 跑完整管线，任务详情页实时展示 4 阶段进度，最终视频落 R2 并可在线预览与下载。背景音乐可选：创建任务时从 4 段预设 BGM 中选择，或上传自定义音频文件（mp3/wav/ogg/flac/m4a/aac，≤50MB）。自定义 BGM 经 JSON+base64 上传存入 R2（key 以 `bgm/` 前缀区分），workflow 检测到该前缀时从 R2 下载到本地再传给 `main.py`。选定 BGM 后 `main.py` 在拼接后混合（视频流零重编码，BGM 循环铺满时长），最终视频以 `final_output.mp4` 上传 R2，下载链接与无 BGM 任务一致。已验证：自定义 BGM 上传 → 创建任务 → workflow 从 R2 下载 → BGM 混合 → 最终 MP4 含音频轨（mean -42.6 dB）。
