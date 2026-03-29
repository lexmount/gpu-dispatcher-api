import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from dotenv import load_dotenv  # <--- 1. 把这个引包加回来

# <--- 2. 把这行读取命令加回来，让它加载你的 Access Key
load_dotenv()

# --- 核心配置 ---
# 直接焊死区域，绝对不让 .env 里的系统变量捣乱！
REGION = "eu-north-1"
ec2_client = boto3.client("ec2", region_name=REGION)
ec2_resource = boto3.resource("ec2", region_name=REGION)

# 你指定的：纯净版 Ubuntu 24.04 (斯德哥尔摩区)
#AMI_ID = "ami-080254318c2d8932f"
AMI_ID = "ami-0b5493a3a9c7dedf9"

app = FastAPI(
    title="GPU IaaS Broker API",
    description="内部底层云主机自动分配与生命周期管理接口",
)

class AllocateRequest(BaseModel):
    user_id: str
    instance_type: str = "g4dn.xlarge"
    #instance_type: str = "t3.medium"
    disk_size_gb: int = 100

def get_or_create_ssh_security_group() -> str:
    """自动创建并获取开放了 22 端口的安全组 ID"""
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
    """查询指定机器的运行状态 (running, stopped, terminated 等)"""
    try:
        instance = ec2_resource.Instance(instance_id)
        instance.load() # 强制从 AWS 拉取最新状态
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
# 接口 3: 销毁机器 (停止扣费)
# ==========================================
@app.delete("/api/v1/terminate/{instance_id}")
async def terminate_instance(instance_id: str):
    """彻底销毁机器，停止计费，释放公网 IP 和硬盘"""
    try:
        instance = ec2_resource.Instance(instance_id)
        response = instance.terminate()
        
        # 修复了这里的解析逻辑，按照 AWS 的字典结构正确取值
        current_state = response['TerminatingInstances'][0]['CurrentState']['Name']
        
        return {
            "status": "success",
            "message": f"实例 {instance_id} 已触发销毁程序",
            "data": {
                "instance_id": instance_id,
                "current_state": current_state # 返回 shutting-down
            }
        }
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"销毁机器失败: {e!s}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"系统内部错误: {e!s}")