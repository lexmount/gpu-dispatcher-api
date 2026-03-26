# SageProxy

单体仓库（Monorepo）：**FastAPI 后端**（`backend/`）、**Vite + React + Tailwind 控制台**（`frontend/`）、**SageCLI**（`cli/`）。生产环境可先 `npm run build`，再由 FastAPI 托管 `frontend/dist`，实现**单端口**全栈访问。

## 目录结构

```
gpu-dispatcher-api/
├── backend/main.py       # FastAPI（uvicorn: backend.main:app）
├── frontend/             # Vite + React + Tailwind（赛博朋克风双视角 UI）
├── cli/                  # sagecli 命令行
├── pyproject.toml        # Python 依赖（uv sync）
└── README.md
```

Python 依赖统一在**仓库根目录** `pyproject.toml` 管理（白皮书中的 `backend/pyproject.toml` 如需可后续再拆分为 uv workspace）。

## 云端配置（管理员）

浏览器将代码包 **PUT 到 S3 预签名 URL** 时，必须在 **S3 桶「权限 → CORS」** 中允许浏览器源与 `PUT`（具体 JSON 以你们桶策略为准；开发阶段可用 `AllowedOrigins: ["*"]` 等，生产收紧）。

## 环境变量（后端）

可将 `.env` 放在**仓库根目录**或 **`backend/.env`**（二者都会被加载，后者优先覆盖同名键）。

```bash
cp .env.example .env
```

至少需要：`AWS_REGION`、`SAGEMAKER_ROLE_ARN`、`S3_BUCKET_NAME`；可选访问密钥、`CORS_ORIGINS` 等。说明见 `.env.example`。

**CORS**：`CORS_ORIGINS=*` 时与 `allow_credentials=False` 搭配（符合 Starlette 限制）。若前端需带 Cookie，请设为逗号分隔的具体源（如 `http://localhost:5173`）。

## 安装与运行

### Python（后端 + CLI）

```bash
uv venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv sync
```

### 前端

```bash
cd frontend && npm install
```

**开发（前后端分离、热更新）**

- 终端 1：`uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
- 终端 2：`cd frontend && npm run dev`（默认 [http://localhost:5173](http://localhost:5173)）

`frontend/.env.development` 中默认 `VITE_API_BASE=http://127.0.0.1:8000`，供 Axios 调用 API。

**生产（单端口：API + 静态页）**

```bash
cd frontend && npm run build
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

若存在 `frontend/dist`，FastAPI 会挂载到 `/`，与 `/docs`、`/admin/*` 等 API 共存；浏览器访问 `http://<host>:8000/` 即控制台。

### SageCLI

```bash
sagecli config
sagecli submit -u <user> -p <prefix>
sagecli status <job_name>
```

## API 摘要

| 用途 | 方法 | 路径 |
|------|------|------|
| 预签名上传 | POST | `/generate-upload-url` |
| 提交训练 | POST | `/submit-job` |
| 任务状态 | GET | `/job-status/{job_name}` |
| 停止任务 | POST | `/stop-job/{job_name}` |
| 管理大盘 | GET | `/admin/stats`（见下） |

`GET /admin/stats` 返回字段包括：`active_count`（进行中作业数）、`total_training_instances`（池内训练实例节点数加总）、`total_gpu_units`（按实例类型映射的 GPU 张数估算）、`jobs_created_today_utc`、`jobs`（含 `instance_type`、`instance_count`、`gpu_units`）、`resource_note`（估算说明）、`as_of_utc`。

Swagger：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

## 控制台功能（前端）

- **开发者终端**：说明「页面用途 → 上传什么 → 目录示例 → 打包命令」，再提供 `.tar.gz` 上传；链路为预签名 → 浏览器直传 S3 → `submit-job`。入口脚本须为 `train.py`（与后端 SageMaker 环境变量一致）。
- **资源与运维**：展示池中 **GPU 估算张数**、**训练节点数**、进行中任务数、UTC 当日新建任务数；表格含实例类型、节点数、GPU(估)、已运行时长；可停止任务。每 10 秒刷新。GPU 由后端按常见实例规格映射，未收录类型有保守启发式，**以 AWS 账单为准**。

模拟用户由 `VITE_CURRENT_USER` 控制（默认见 `frontend/.env.development`）。

## 安全说明

- 训练任务在服务端设置 `MaxRuntimeInSeconds`。
- **管理接口与控制台当前无登录鉴权**，仅适合内网或受信环境；生产需 HTTPS、认证与最小权限 IAM。

## 后续可做

- [ ] API Key / 登录  
- [ ] 额度与扣费  
- [ ] 任务与账单落库统计  
