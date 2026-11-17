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
    ├── deploy-backend.yml      # 后端部署（含前端构建）
    └── deploy-frontend.yml     # 前端构建验证
```

## 二、Cloudflare 资源

| 资源 | 名称 | 说明 |
|---|---|---|
| Worker | `pexel-remotion-worker` | 后端 API + 前端静态资源，绑定自定义域名 `pere.ygtxl.dpdns.org` |
| D1 | `pexel-remotion-db` | SQLite 数据库 |
| R2 | `pexel-remotion-bucket` | 产物存储（视频、分镜、匹配结果等） |

> **架构说明**：前端通过 Worker 的 `assets` 绑定提供静态文件，SPA 路由由 `not_found_handling = "single-page-application"` 处理。API 路径 `/api/*` 由 Worker 的 Hono 路由处理，非 API 路径由 assets 绑定提供静态文件。无需单独的 Pages 项目。

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
| `GH_PAT` | GitHub Personal Access Token（repo, workflow scope；不能以 `GITHUB_` 开头） |
| `FRONTEND_URL` | 前端地址（`https://pere.ygtxl.dpdns.org`） |
| `R2_PUBLIC_URL` | R2 公开访问 URL |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API Token（用于缓存清除） |

### 前端部署（deploy-frontend.yml）

此 workflow 仅用于前端构建验证和产物上传，实际部署由 `deploy-backend.yml` 在构建前端后随 Worker 一起部署。

## 三之二、Worker 运行时变量（重要）

`wrangler.toml` 里的 `[vars]` **不会**做 `${VAR}` 插值 —— wrangler 会把 `"${JWT_SECRET}"` 原样当字符串上传。
因此所有密钥必须用下面的方式写入，且**不要**在 `wrangler.toml` 中声明：

```bash
cd backend
npx wrangler secret put JWT_SECRET
# 或在 CI 中：printf '%s' "$JWT_SECRET" | npx wrangler secret put JWT_SECRET
```

需要写入的密钥：`ADMIN_API_KEY`、`CALLBACK_SECRET`、`JWT_SECRET`、`ENCRYPTION_KEY`、`GITHUB_PAT`、`CLOUDFLARE_API_TOKEN`。
`deploy-backend.yml` 已包含「配置 Worker Secrets」步骤自动完成这一步。

验证是否生效：

```bash
curl -s -H "Authorization: Bearer $CF_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/workers/scripts/pexel-remotion-worker/settings" \
  | jq '.result.bindings[] | {name, type}'
# 密钥应为 secret_text，绝不能出现 text: "${...}"
```

## 三之三、CI 环境要求

- **Node.js ≥ 22.12**：wrangler 4 已不支持 Node 20，三个 workflow 均已固定为 `node-version: "22"`。
- `@cloudflare/workers-types` 必须为 `^5`，否则 `npm install` 会因 wrangler 4 的 peer 依赖冲突而失败。
- PowerShell 步骤中调用外部程序要用参数数组展开，不能写 `& $cmd`（会被当成单个命令名）：

  ```powershell
  $exe = $cmd[0]
  $argsList = @($cmd[1..($cmd.Count - 1)])
  & $exe @argsList
  ```

- `repository_dispatch` 的 `client_payload` 只能通过 `$env:GITHUB_EVENT_PATH` 指向的 JSON 文件读取，
  GitHub Actions 不存在 `GITHUB_EVENT` 这个变量。

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

### 3. 部署后端（含前端）

修改 `backend/wrangler.toml` 中的 `database_id` 后，推送 `backend/` 或 `frontend/` 目录的变更到 `main` 分支，`deploy-backend.yml` 会自动构建前端并部署 Worker。

或手动部署：

```bash
# 先构建前端
cd frontend
npm install
npm run build

# 再部署后端（Worker 会自动打包前端 assets）
cd ../backend
npx wrangler deploy
```

### 4. 配置自定义域名

在 Cloudflare Dashboard → Workers & Pages → `pexel-remotion-worker` → Settings → Triggers → Custom Domains 中添加 `pere.ygtxl.dpdns.org`。

> **注意**：Worker 通过 `wrangler.toml` 中的 `[[routes]]` 配置已自动绑定自定义域名，所有请求（API + 前端）均由 Worker 统一处理。

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
