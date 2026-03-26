# SageProxy Backend

SageProxy Backend 是一个基于 FastAPI 构建的中间层服务。它的核心职责是安全地代理外部用户的计算请求，并将其转化为 AWS SageMaker Training Jobs，从而实现 GPU 资源的按需调度与自动释放。

## 架构总览

| 类别 | 说明 |
|------|------|
| 框架 | FastAPI (Python 3.10+) |
| 云服务 | AWS SageMaker（计算）、Amazon S3（存储） |
| 核心依赖 | `boto3`、`uvicorn`、`pydantic`、`python-dotenv` |

## 本地开发与运行

### 1. 环境准备

确保本地已配置具备相应权限的 AWS 凭证：

```bash
aws configure
```

### 2. 安装依赖（推荐 uv）

[uv](https://docs.astral.sh/uv/) 会在项目根目录创建 `.venv` 并安装 `pyproject.toml` 中的依赖：

```bash
uv venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv sync
```

若未安装 uv，可先 `curl -LsSf https://astral.sh/uv/install.sh | sh`，或使用 `pip install uv`。

### 3. 环境变量

复制示例文件并编辑（勿将真实密钥提交到 Git）：

```bash
cp .env.example .env
```

`.env` 中至少需要配置：

```env
AWS_REGION=eu-north-1
SAGEMAKER_ROLE_ARN=arn:aws:iam::YOUR_ACCOUNT_ID:role/YourSageMakerRole
S3_BUCKET_NAME=your-s3-bucket-name
```

若在本地用 **访问密钥**（或 STS 临时凭证）调用 AWS API，可同时配置：

```env
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
# 临时凭证时需要
# AWS_SESSION_TOKEN=...
```

未配置密钥时仍可使用本机默认凭证链（例如已 `aws configure` 的配置文件、工作负载身份等）。

### 4. 启动服务

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) 查看 Swagger 文档并调试接口。

## 安全与计费准则

- **硬性超时**：所有 SageMaker 任务必须设置 `MaxRuntimeInSeconds`，避免僵尸任务持续计费。
- **实例限制**：默认仅允许调度高性价比实例（如 `ml.g4dn.xlarge`）。

## TODO

- [ ] 接入数据库（DynamoDB / RDS）进行 API Key 鉴权
- [ ] 实现额度 / 余额扣减逻辑
- [ ] 完善 S3 Presigned URL 上传与下载接口
