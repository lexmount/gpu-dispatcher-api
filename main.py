import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
# 1. 引入 Depends, status 和 APIKeyHeader (用于鉴权)
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# --- 核心配置 ---
REGION = "eu-north-1"
ec2_client = boto3.client("ec2", region_name=REGION)
ec2_resource = boto3.resource("ec2", region_name=REGION)

AMI_ID = "ami-0b5493a3a9c7dedf9"

# ==========================================
# 🔐 鉴权配置模块 (新增)
# ==========================================
# 规定请求头里必须包含一个叫 "X-API-Key" 的字段
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

# 从环境变量读取密码，如果没有配置，默认使用 "lexmount"
EXPECTED_API_KEY = os.getenv("API_KEY", "lexmount")

async def verify_api_key(api_key: str = Depends(api_key_header)):
    """校验传入的 Key 是否正确"""
    if api_key != EXPECTED_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="不好意思，你的 API Key 错误或未授权！",
        )
    return api_key

# ==========================================
# 初始化 FastAPI (加上全局门禁)
# ==========================================
# 2. 在 app 初始化时，加上 dependencies 参数，这样所有接口都会强制校验！
app = FastAPI(
    title="GPU IaaS Broker API",
    description="内部底层云主机自动分配与生命周期管理接口",
    dependencies=[Depends(verify_api_key)] 
)

class AllocateRequest(BaseModel):
    user_id: str
    instance_type: str = "g4dn.xlarge"
    disk_size_gb: int = 100

def get_or_create_ssh_security_group() -> str:
    sg_name = "sageproxy-ssh-sg"
    try:
        response = ec2_client.describe_security_groups(GroupNames=[sg_name])
        return response['SecurityGroups'][0]['GroupId']
    except ClientError as e:
        if 'InvalidGroup.NotFound' in str(e):
            print("🛡️ 未找到专属安全组，正在自动创建并开放 22 端口...")
            response = ec2_client.create_security_group(
                GroupName=sg_name,
                Description="Auto-generated SG for SageProxy to allow SSH access"
            )
            sg_id = response['GroupId']
            ec2_client.authorize_security_group_ingress(
                GroupId=sg_id,
                IpPermissions=[{
                    'IpProtocol': 'tcp',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                }]
            )
            return sg_id
        raise e

# ==========================================
# 接口 1: 申请开机
# ==========================================
@app.post("/api/v1/allocate-gpu")
async def allocate_gpu_instance(req: AllocateRequest):
    try:
        sg_id = get_or_create_ssh_security_group()

        timestamp = int(time.time())
        key_name = f"gpu-key-{req.user_id}-{timestamp}"
        key_pair_response = ec2_client.create_key_pair(KeyName=key_name)
        private_key_pem = key_pair_response["KeyMaterial"]

        print(f"🚀 正在为 {req.user_id} 拉起 {req.instance_type} 实例 (AMI: {AMI_ID})...")
        instances = ec2_resource.create_instances(
            ImageId=AMI_ID,
            InstanceType=req.instance_type,
            MinCount=1,
            MaxCount=1,
            KeyName=key_name,
            SecurityGroupIds=[sg_id],
            BlockDeviceMappings=[{
                "DeviceName": "/dev/sda1",
                "Ebs": {"VolumeSize": req.disk_size_gb, "VolumeType": "gp3", "DeleteOnTermination": True}
            }],
            TagSpecifications=[{
                "ResourceType": "instance",
                "Tags": [
                    {"Key": "Name", "Value": f"Allocated-GPU-{req.user_id}"},
                    {"Key": "Owner", "Value": req.user_id},
                ]
            }],
        )

        instance = instances[0]
        print(f"⏳ 实例 {instance.id} 已建立，等待网络初始化...")
        instance.wait_until_running()
        instance.reload()

        public_ip = instance.public_ip_address
        if not public_ip:
            raise RuntimeError("未能成功获取公网 IP")

        escaped_pem = private_key_pem.replace('"', '\\"')
        one_click_command = f"""echo -e "{escaped_pem}" > {key_name}.pem && chmod 400 {key_name}.pem && ssh -o ServerAliveInterval=60 -o StrictHostKeyChecking=no -i {key_name}.pem ubuntu@{public_ip}"""

        return {
            "status": "success",
            "message": "GPU 资源分配成功",
            "data": {
                "instance_id": instance.id,
                "public_ip": public_ip,
                "ssh_username": "ubuntu",
                "private_key": private_key_pem,
                "one_click_login_script": one_click_command
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"底层开机失败: {e!s}")

# ==========================================
# 接口 2: 查询状态
# ==========================================
@app.get("/api/v1/status/{instance_id}")
async def check_instance_status(instance_id: str):
    try:
        instance = ec2_resource.Instance(instance_id)
        instance.load()
        return {
            "status": "success",
            "data": {
                "instance_id": instance.id,
                "state": instance.state['Name'],
                "public_ip": instance.public_ip_address
            }
        }
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"查不到这台机器: {e!s}")

# ==========================================
# 接口 3: 销毁机器
# ==========================================
@app.delete("/api/v1/terminate/{instance_id}")
async def terminate_instance(instance_id: str):
    try:
        instance = ec2_resource.Instance(instance_id)
        response = instance.terminate()
        current_state = response['TerminatingInstances'][0]['CurrentState']['Name']
        return {
            "status": "success",
            "message": f"实例 {instance_id} 已触发销毁程序",
            "data": {
                "instance_id": instance_id,
                "current_state": current_state
            }
        }
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"销毁机器失败: {e!s}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"系统内部错误: {e!s}")