# GPU Instance Broker API

基于 FastAPI 的轻量 REST 服务：算法侧通过 `POST /api/v1/allocate-gpu` 申请 GPU EC2，接口返回公网 IP 与 SSH 私钥。无前端、无 SageMaker / S3 上传逻辑。

详细约定与联调说明见仓库根目录 [develop.md](develop.md)。

## 依赖与启动

```bash
uv venv .venv && source .venv/bin/activate
uv sync
cp .env.example .env   # 填入具有 EC2 权限的 AWS 凭证
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

交互文档：<http://127.0.0.1:8000/docs>

## 调用方保存密钥

将响应中的 `private_key` 写入 `my_key.pem`，执行：

```bash
chmod 400 my_key.pem
ssh -i my_key.pem ubuntu@<public_ip>
```
