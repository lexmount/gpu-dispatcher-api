🚀 内部 GPU 调度核心 (EC2 Broker API) 开发指南
🎯 业务目标
我们的任务是开发一个极其轻量级的 RESTful API 服务 (基于 FastAPI)。
不需要开发任何 Web 前端界面。
算法团队（李鹏坤那边）会通过脚本调用我们的 API 来申请 GPU 机器，我们的接口负责在 AWS 上动态拉起虚拟机，并将 公网 IP 和 SSH 私钥 直接返回给他们。

🧹 历史清理（极其重要）
之前的 sagemaker 相关的代码、依赖全部删除。

之前的 上传 tar.gz 到 S3 相关的逻辑全部删除。

之前写的任何 前端 UI 组件 统统作废删除。

📦 前置准备
在虚拟环境中安装最新的依赖：

Bash
pip install fastapi uvicorn boto3
确保项目根目录的 .env 文件包含最新的 AWS IAM 密钥（具有 EC2 权限）。

💻 核心代码实现
在项目中新建一个纯净的 main.py 文件，完整粘贴以下代码。这是整个系统唯一的代码。

Python
import time
import os
import boto3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# 初始化 FastAPI
app = FastAPI(title="GPU Instance Broker API", description="内部底层云主机自动分配接口")

# 初始化 AWS EC2 客户端 (固定区域为斯德哥尔摩)
REGION = 'eu-north-1'
ec2_client = boto3.client('ec2', region_name=REGION)
ec2_resource = boto3.resource('ec2', region_name=REGION)

# --- 核心配置 ---
# 这是一个预装了 PyTorch, CUDA, Docker 等深度学习环境的官方 Ubuntu 22.04 镜像 (AMI)
# 必须使用与 eu-north-1 区域匹配的 AMI ID，以下为示例深度学习 AMI ID
DEEP_LEARNING_AMI_ID = "ami-055375c3dbfb0d1a4" # 请管理员在 AWS EC2 控制台核实并替换最新 ID

class AllocateRequest(BaseModel):
    user_id: str
    instance_type: str = "g4dn.xlarge" # 默认单卡 T4
    disk_size_gb: int = 100

@app.post("/api/v1/allocate-gpu")
async def allocate_gpu_instance(req: AllocateRequest):
    """
    核心接口：为请求用户开通一台专属的 GPU 虚拟机，并返回 SSH 凭证
    """
    try:
        # 1. 动态生成一次性 SSH 密钥对，确保每个机器独立且安全
        timestamp = int(time.time())
        key_name = f"gpu-key-{req.user_id}-{timestamp}"
        
        # 请求 AWS 生成密钥
        key_pair_response = ec2_client.create_key_pair(KeyName=key_name)
        private_key_pem = key_pair_response['KeyMaterial']

        # 2. 调用 EC2 接口正式开机
        print(f"🚀 正在为 {req.user_id} 拉起 {req.instance_type} 实例...")
        instances = ec2_resource.create_instances(
            ImageId=DEEP_LEARNING_AMI_ID,
            InstanceType=req.instance_type,
            MinCount=1,
            MaxCount=1,
            KeyName=key_name,
            BlockDeviceMappings=[{
                'DeviceName': '/dev/sda1',
                'Ebs': {
                    'VolumeSize': req.disk_size_gb,
                    'VolumeType': 'gp3',
                    'DeleteOnTermination': True # 关机时自动删除硬盘数据以省钱
                }
            }],
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [
                    {'Key': 'Name', 'Value': f'Allocated-GPU-{req.user_id}'},
                    {'Key': 'Owner', 'Value': req.user_id}
                ]
            }]
        )
        
        instance = instances[0]
        
        # 3. 阻塞等待机器分配到真实的公网 IP
        print(f"⏳ 实例 {instance.id} 已建立，等待网络初始化...")
        instance.wait_until_running()
        instance.reload() # 刷新对象以获取最新的公网 IP 属性
        
        public_ip = instance.public_ip_address
        if not public_ip:
            raise Exception("未能成功获取公网 IP")

        # 4. 组装返回结果
        return {
            "status": "success",
            "message": "GPU 资源分配成功",
            "data": {
                "instance_id": instance.id,
                "public_ip": public_ip,
                "ssh_username": "ubuntu",
                "ssh_command": f"ssh -i private_key.pem ubuntu@{public_ip}",
                "private_key": private_key_pem
            }
        }

    except Exception as e:
        print(f"❌ 分配失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"底层资源调度失败: {str(e)}")

# 你可以通过 uvicorn main:app --reload 启动此服务
# 测试：去浏览器打开 http://127.0.0.1:8000/docs 使用 Swagger UI 发送测试请求
🛠️ 测试与联调步骤
本地启动服务：uvicorn main:app --reload

算法团队（调用方）通过 POST 请求访问该接口，如果成功，他们会收到一段完整的 private_key 字符串。

调用方操作指导：调用方需要将返回的 private_key 字符串保存到本地，命名为 my_key.pem。然后在终端执行：

Bash
chmod 400 my_key.pem  # (必须，否则 SSH 会拒绝太开放的密钥文件)
ssh -i my_key.pem ubuntu@<返回的IP地址>