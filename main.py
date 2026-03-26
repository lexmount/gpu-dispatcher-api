import os
import time

import boto3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

load_dotenv()

app = FastAPI(title="GPU Resource Scheduler API")

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
    """查看当前账户下状态为 InProgress 的训练任务（便于盯计费）。"""
    try:
        response = sm_client.list_training_jobs(
            StatusEquals="InProgress",
            SortBy="CreationTime",
            SortOrder="Descending",
            MaxResults=50,
        )
        summaries = response.get("TrainingJobSummaries", [])
        jobs = [
            {
                "job_name": j["TrainingJobName"],
                "creation_time": j["CreationTime"].isoformat(),
            }
            for j in summaries
        ]
        return {
            "active_count": len(jobs),
            "jobs": jobs,
            "next_token": response.get("NextToken"),
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
