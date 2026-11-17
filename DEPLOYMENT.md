# Pere — 部署指南

> 图文转视频自动生成平台，基于 Remotion + Pexels，部署在 Cloudflare。

## 一、项目结构

```
pere/
├── main.py                      # 视频生成主流程（CLI，支持 CI 模式）
├── core/                       # 核心模块（分镜、素材匹配、渲染、合成）
├── remotion/                   # Remotion 场景模板
├── config/                     # 配置文件（已脱敏）
├── backend/                    # Cloudflare Workers 后端 API
│   ├── src/
│   │   ├── index.ts            # Hono 应用入口
│   │   ├── services/           # CryptoService, TaskService
│   │   ├── routes/             # auth, tasks, callback, files, admin
│   │   ├── middleware/         # auth, error, logger
│   │   ├── types/              # 类型定义
│   │   ├── database/           # D1 schema
│   │   └── scheduled.ts        # 定时任务
│   ├── wrangler.toml           # Worker 配置
│   └── package.json
├── frontend/                   # React + Vite 前端
│   ├── src/
│   │   ├── App.tsx             # 路由
│   │   ├── pages/              # Login, Dashboard, CreateTask, TaskDetail
│   │   ├── components/         # Layout, ProgressBar
│   │   ├── context/            # AuthContext
│   │   ├── api/                # API 客户端
│   │   └── types.ts            # 类型定义
│   ├── vite.config.ts
│   └── package.json
└── .github/workflows/          # GitHub Actions
    ├── video-generation.yml    # 视频生成（repository_dispatch）
    ├── deploy-backend.yml      # 后端部署
    └── deploy-frontend.yml     # 前端部署
```

## 二、Cloudflare 资源

| 资源 | 名称 | 说明 |
|---|---|---|
| Worker | `pexel-remotion-worker` | 后端 API，绑定自定义域名 `pere.ygtxl.dpdns.org` |
| D1 | `pexel-remotion-db` | SQLite 数据库 |
| R2 | `pexel-remotion-bucket` | 产物存储（视频、分镜、匹配结果等） |
| Pages | `pexel-remotion-frontend` | 前端静态站点，绑定 `pere.ygtxl.dpdns.org` |

## 三、GitHub Actions Secrets

在仓库 `Settings → Secrets and variables → Actions` 中配置以下 Secrets：

### 视频生成（video-generation.yml）

| Secret | 说明 |
|---|---|
| `ZHIPU_API_KEY` | 智谱 AI API Key（多模态评审） |
| `AGNES_API_KEY` | Agnes AI API Key（文章生成、分镜） |
| `PEXELS_API_KEY` | Pexels API Key（素材下载） |
| `R2_BUCKET_NAME` | R2 桶名（`pexel-remotion-bucket`） |
| `R2_ACCESS_KEY_ID` | R2 Access Key ID |
| `R2_SECRET_ACCESS_KEY` | R2 Secret Access Key |
| `R2_ENDPOINT_URL` | R2 Endpoint URL |
| `CALLBACK_URL` | 后端回调地址（`https://pere.ygtxl.dpdns.org/api/v1/callback/github`） |
| `CALLBACK_SECRET` | 回调签名密钥 |

### 后端部署（deploy-backend.yml）

| Secret | 说明 |
|---|---|
| `ADMIN_API_KEY` | 管理员 API Key |
| `CALLBACK_SECRET` | 回调签名密钥（与视频生成一致） |
| `JWT_SECRET` | JWT 签名密钥（至少 32 字节） |
| `ENCRYPTION_KEY` | AES-GCM 加密密钥（至少 32 字节） |
| `GITHUB_PAT` | GitHub Personal Access Token（repo, workflow scope） |
| `FRONTEND_URL` | 前端地址（`https://pere.ygtxl.dpdns.org`） |
| `R2_PUBLIC_URL` | R2 公开访问 URL |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API Token（用于缓存清除） |

### 前端部署（deploy-frontend.yml）

| Secret | 说明 |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare API Token |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare 账户 ID |

## 四、环境变量生成

使用以下命令生成安全的密钥：

```bash
# JWT Secret（32 字节）
openssl rand -base64 32

# Encryption Key（32 字节）
openssl rand -base64 32

# Admin API Key
openssl rand -hex 24

# Callback Secret
openssl rand -hex 24
```

## 五、部署流程

### 1. 首次部署 D1 数据库

```bash
cd backend
npx wrangler d1 create pexel-remotion-db
# 将输出的 database_id 填入 wrangler.toml

# 执行数据库迁移
npx wrangler d1 execute pexel-remotion-db --file=./src/database/schema.sql --remote
```

### 2. 首次部署 R2 桶

```bash
npx wrangler r2 bucket create pexel-remotion-bucket
```

### 3. 部署后端

修改 `backend/wrangler.toml` 中的 `database_id` 后，推送 `backend/` 目录的变更到 `main` 分支，`deploy-backend.yml` 会自动部署。

或手动部署：

```bash
cd backend
npx wrangler deploy
```

### 4. 部署前端

推送 `frontend/` 目录的变更到 `main` 分支，`deploy-frontend.yml` 会自动构建并部署到 Cloudflare Pages。

或手动部署：

```bash
cd frontend
npm run build
# 通过 Cloudflare Pages 部署 dist 目录
```

### 5. 配置自定义域名

- Worker：在 Cloudflare Dashboard → Workers & Pages → `pexel-remotion-worker` → Settings → Triggers → Custom Domains 中添加 `pere.ygtxl.dpdns.org`
- Pages：在 Cloudflare Dashboard → Workers & Pages → `pexel-remotion-frontend` → Settings → Custom Domains 中添加 `pere.ygtxl.dpdns.org`

> **注意**：Worker 和 Pages 共用同一域名时，需要配置 Worker 路由，将 `/api/*` 路径路由到 Worker，其余路径由 Pages 处理。

## 六、默认账号

| 用户名 | 密码 | 角色 |
|---|---|---|
| admin | admin123 | ADMIN |

> 首次登录后建议通过管理 API 修改密码。

## 七、任务流程

1. 用户在前端登录，创建任务（选择文章来源：AI 生成 / 粘贴 / 上传）
2. 后端创建任务记录，通过 `repository_dispatch` 触发 GitHub Actions workflow
3. Workflow 按阶段执行：分镜生成 → 素材匹配 → Remotion 渲染 → 语音合成
4. 每个阶段完成后：
   - 中间产物上传到 R2（`tasks/{task_id}/`）
   - 回调通知后端更新进度
5. 全部完成后，前端可预览和下载最终视频

## 八、本地开发

### 后端

```bash
cd backend
cp .dev.vars.example .dev.vars
# 编辑 .dev.vars 填入实际值
npx wrangler dev
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端开发服务器会在 `http://localhost:5173` 启动，API 请求代理到 `http://localhost:8787`（Wrangler 开发服务器）。
