import os
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

_backend_dir = Path(__file__).resolve().parent
_repo_root = _backend_dir.parent
load_dotenv(_backend_dir / ".env")
load_dotenv(_repo_root / ".env")

app = FastAPI(title="SageProxy API")

# CORS：浏览器直传 S3 不经过此处；此处供 Vite 开发机 (5173) 等访问 API。
# allow_origins=* 时 Starlette 要求 allow_credentials=False；需带 Cookie 时请列出具体源。
_cors_origins = os.getenv("CORS_ORIGINS", "*").strip()
if _cors_origins == "*":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ================= AWS / SageMaker 配置（环境变量 + .env）=================

AWS_REGION = os.getenv("AWS_REGION", "eu-north-1")
SAGEMAKER_ROLE_ARN = os.getenv("SAGEMAKER_ROLE_ARN", "").strip()
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "").strip()
DEFAULT_TRAINING_IMAGE_URI = (
    "763104351884.dkr.ecr.eu-north-1.amazonaws.com/pytorch-training:"
    "2.0.0-gpu-py310-cu118-ubuntu20.04-sagemaker"
)
TRAINING_IMAGE_URI = os.getenv("TRAINING_IMAGE_URI", DEFAULT_TRAINING_IMAGE_URI).strip()

# 预签名 PUT 有效期（秒）
PRESIGNED_PUT_EXPIRES = int(os.getenv("PRESIGNED_PUT_EXPIRES", "3600"))


def _boto_client_kwargs() -> dict:
    """
    若设置了静态密钥或临时会话（STS），显式传给 boto3。
    未设置时走默认凭证链（环境变量已由 load_dotenv 注入，或由 ~/.aws、credentials 等接管）。
    """
    key_id = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
    secret = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
    token = os.getenv("AWS_SESSION_TOKEN", "").strip()
    if not key_id or not secret:
        return {}
    kw: dict = {
        "aws_access_key_id": key_id,
        "aws_secret_access_key": secret,
    }
    if token:
        kw["aws_session_token"] = token
    return kw


sm_client = boto3.client("sagemaker", region_name=AWS_REGION, **_boto_client_kwargs())
s3_client = boto3.client("s3", region_name=AWS_REGION, **_boto_client_kwargs())


def _require_role_and_bucket() -> None:
    if not SAGEMAKER_ROLE_ARN or not S3_BUCKET_NAME:
        raise HTTPException(
            status_code=503,
            detail="服务未配置：请在环境变量或 .env 中设置 SAGEMAKER_ROLE_ARN 与 S3_BUCKET_NAME",
        )


def _require_bucket() -> None:
    if not S3_BUCKET_NAME:
        raise HTTPException(
            status_code=503,
            detail="服务未配置：请在环境变量或 .env 中设置 S3_BUCKET_NAME",
        )


def _user_id_from_job_name(job_name: str) -> str:
    """任务名格式 {prefix}-{user_id}-{unix_ts}，user_id 中不含 '-'。"""
    parts = job_name.rsplit("-", 2)
    if len(parts) == 3 and parts[2].isdigit():
        return parts[1]
    return "—"


def _list_in_progress_jobs() -> list[dict]:
    out: list[dict] = []
    token: str | None = None
    while True:
        kwargs: dict = {
            "StatusEquals": "InProgress",
            "SortBy": "CreationTime",
            "SortOrder": "Descending",
            "MaxResults": 100,
        }
        if token:
            kwargs["NextToken"] = token
        resp = sm_client.list_training_jobs(**kwargs)
        for j in resp.get("TrainingJobSummaries", []):
            name = j["TrainingJobName"]
            ct = j["CreationTime"]
            out.append(
                {
                    "job_name": name,
                    "creation_time": ct.isoformat(),
                    "status": j.get("TrainingJobStatus", "InProgress"),
                    "user_id": _user_id_from_job_name(name),
                }
            )
        token = resp.get("NextToken")
        if not token:
            break
    return out


def _count_jobs_created_since(since: datetime) -> int:
    total = 0
    token: str | None = None
    while True:
        kwargs: dict = {
            "CreationTimeAfter": since,
            "SortBy": "CreationTime",
            "SortOrder": "Descending",
            "MaxResults": 100,
        }
        if token:
            kwargs["NextToken"] = token
        resp = sm_client.list_training_jobs(**kwargs)
        total += len(resp.get("TrainingJobSummaries", []))
        token = resp.get("NextToken")
        if not token:
            break
    return total


# 常见 SageMaker 训练实例：单节点 GPU 数量（与 AWS 文档一致；未列出类型走启发式）
_GPU_PER_INSTANCE: dict[str, int] = {
    "ml.g4dn.xlarge": 1,
    "ml.g4dn.2xlarge": 1,
    "ml.g4dn.4xlarge": 1,
    "ml.g4dn.8xlarge": 1,
    "ml.g4dn.12xlarge": 4,
    "ml.g4dn.16xlarge": 1,
    "ml.g5.xlarge": 1,
    "ml.g5.2xlarge": 1,
    "ml.g5.4xlarge": 1,
    "ml.g5.8xlarge": 1,
    "ml.g5.12xlarge": 4,
    "ml.g5.16xlarge": 1,
    "ml.g5.24xlarge": 4,
    "ml.g5.48xlarge": 8,
    "ml.p3.2xlarge": 1,
    "ml.p3.8xlarge": 4,
    "ml.p3.16xlarge": 8,
    "ml.p4d.24xlarge": 8,
    "ml.p4de.24xlarge": 8,
    "ml.m5.large": 0,
    "ml.m5.xlarge": 0,
    "ml.m5.2xlarge": 0,
    "ml.c5.xlarge": 0,
}


def _gpu_units_for_instance(instance_type: str, instance_count: int) -> int:
    """估算任务占用的 GPU「张」数（同类型多节点会相乘）。"""
    t = instance_type.strip()
    ic = max(instance_count, 1)
    if t in _GPU_PER_INSTANCE:
        return _GPU_PER_INSTANCE[t] * ic
    tl = t.lower()
    if any(x in tl for x in ("ml.g4", "ml.g5", "ml.p2", "ml.p3", "ml.p4", "ml.p5")):
        return ic  # 未收录的 GPU 族：保守按每节点 1 卡
    return 0


def _describe_job_instance(job_name: str) -> tuple[str, int]:
    r = sm_client.describe_training_job(TrainingJobName=job_name)
    rc = r.get("ResourceConfig") or {}
    it = str(rc.get("InstanceType", "unknown"))
    ic = int(rc.get("InstanceCount") or 1)
    return it, max(ic, 1)


def _enrich_jobs_with_resources(jobs: list[dict]) -> list[dict]:
    """为每个任务补充实例类型、节点数、GPU 估算（依赖 DescribeTrainingJob）。"""
    out: list[dict] = []
    for j in jobs:
        name = j["job_name"]
        try:
            it, ic = _describe_job_instance(name)
            gpu = _gpu_units_for_instance(it, ic)
        except Exception:
            it, ic, gpu = "unknown", 1, 0
        row = {**j, "instance_type": it, "instance_count": ic, "gpu_units": gpu}
        out.append(row)
    return out


def _aggregate_pool_stats(enriched: list[dict]) -> tuple[int, int]:
    """返回 (训练实例节点总数, GPU 张数估算总和)。"""
    nodes = sum(int(j.get("instance_count", 1)) for j in enriched)
    gpus = sum(int(j.get("gpu_units", 0)) for j in enriched)
    return nodes, gpus


# ================= 调度与查询 =================


class JobRequest(BaseModel):
    user_id: str
    script_s3_uri: str  # 例如 s3://bucket/user/code/（CLI 已上传完成）
    job_name_prefix: str = "cli-gpu-job"


@app.post("/submit-job", summary="提交 GPU 训练任务")
async def submit_gpu_job(request: JobRequest):
    """接收 CLI 请求，创建 SageMaker 训练任务。"""
    _require_role_and_bucket()

    timestamp = int(time.time())
    job_name = f"{request.job_name_prefix}-{request.user_id}-{timestamp}"
    output_s3_uri = f"s3://{S3_BUCKET_NAME}/outputs/{request.user_id}/{job_name}/"

    try:
        response = sm_client.create_training_job(
            TrainingJobName=job_name,
            RoleArn=SAGEMAKER_ROLE_ARN,
            AlgorithmSpecification={
                "TrainingImage": TRAINING_IMAGE_URI,
                "TrainingInputMode": "File",
            },
            InputDataConfig=[
                {
                    "ChannelName": "code",
                    "DataSource": {
                        "S3DataSource": {
                            "S3DataType": "S3Prefix",
                            "S3Uri": request.script_s3_uri,
                            "S3DataDistributionType": "FullyReplicated",
                        }
                    },
                }
            ],
            OutputDataConfig={"S3OutputPath": output_s3_uri},
            ResourceConfig={
                "InstanceType": "ml.m5.large",
                "InstanceCount": 1,
                "VolumeSizeInGB": 30,
            },
            StoppingCondition={"MaxRuntimeInSeconds": 3600},
            Environment={
                "SAGEMAKER_PROGRAM": "train.py",
                "SAGEMAKER_SUBMIT_DIRECTORY": request.script_s3_uri,
            },
        )
        return {
            "status": "success",
            "message": "GPU 任务已提交，正在排队或启动实例",
            "job_name": job_name,
            "training_job_arn": response["TrainingJobArn"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"提交任务失败: {e}") from e


@app.get("/job-status/{job_name}", summary="查询任务状态")
async def get_job_status(job_name: str):
    try:
        response = sm_client.describe_training_job(TrainingJobName=job_name)
        return {
            "job_name": job_name,
            "status": response["TrainingJobStatus"],
            "secondary_status": response.get("SecondaryStatus", ""),
        }
    except Exception:
        raise HTTPException(status_code=404, detail="找不到该任务或查询失败")


# ================= 停止任务 / 管理监控 =================


@app.post("/stop-job/{job_name}", summary="强制停止训练任务并释放 GPU")
async def stop_job(job_name: str):
    """CLI 主动取消或管理员强制结束仍在运行的训练任务。"""
    try:
        sm_client.stop_training_job(TrainingJobName=job_name)
        return {
            "status": "success",
            "message": f"已请求停止 {job_name}，实例正在释放",
            "job_name": job_name,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"终止任务失败: {e}") from e


@app.get("/admin/active-jobs", summary="列出进行中的训练任务")
async def list_active_jobs():
    """查看当前账户下状态为 InProgress 的训练任务（便于盯计费）。自动翻页，含实例与 GPU 估算。"""
    try:
        jobs = _enrich_jobs_with_resources(_list_in_progress_jobs())
        nodes, gpus = _aggregate_pool_stats(jobs)
        return {
            "active_count": len(jobs),
            "total_training_instances": nodes,
            "total_gpu_units": gpus,
            "jobs": jobs,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/admin/stats", summary="获取全局大盘数据")
async def admin_stats():
    """进行中任务、池内节点/GPU 估算、当日 UTC 新建任务数、任务明细。"""
    try:
        raw = _list_in_progress_jobs()
        jobs = _enrich_jobs_with_resources(raw)
        nodes, gpus = _aggregate_pool_stats(jobs)
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_created = _count_jobs_created_since(day_start)
        return {
            "active_count": len(jobs),
            "total_training_instances": nodes,
            "total_gpu_units": gpus,
            "jobs_created_today_utc": today_created,
            "jobs": jobs,
            "as_of_utc": now.isoformat(),
            "resource_note": (
                "gpu_units 按实例类型映射常见规格估算；未收录的 GPU 族按每节点 1 卡保守估计，"
                "与 AWS 控制台计费明细可能略有差异。"
            ),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# ================= 预签名上传 =================


class UploadRequest(BaseModel):
    file_name: str = Field(..., description="例如 code.tar.gz")
    user_id: str

    @field_validator("file_name")
    @classmethod
    def safe_file_name(cls, v: str) -> str:
        name = os.path.basename(v.strip())
        if not name or name in (".", ".."):
            raise ValueError("无效的文件名")
        return name


@app.post("/generate-upload-url", summary="获取 S3 预签名上传 URL")
async def generate_upload_url(request: UploadRequest):
    """
    CLI 在 submit-job 前调用：拿到临时 PUT URL，直传 S3，再到 submit-job 传入返回的 s3_uri。
    """
    _require_bucket()

    key = f"inputs/{request.user_id}/{int(time.time())}/{request.file_name}"
    try:
        upload_url = s3_client.generate_presigned_url(
            "put_object",
            Params={"Bucket": S3_BUCKET_NAME, "Key": key},
            ExpiresIn=PRESIGNED_PUT_EXPIRES,
        )
        return {
            "upload_url": upload_url,
            "s3_uri": f"s3://{S3_BUCKET_NAME}/{key}",
            "expires_in_seconds": PRESIGNED_PUT_EXPIRES,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成上传链接失败: {e}") from e


# ================= 前端静态资源（npm run build 后由 FastAPI 单端口托管）=================

_frontend_dist = _repo_root / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="spa")
