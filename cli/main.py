"""Typer CLI：sagecli 入口。"""

from __future__ import annotations

import os
from pathlib import Path

import requests
import typer
from requests.exceptions import HTTPError, RequestException
from rich.console import Console
from rich.panel import Panel

from cli.utils import (
    CONFIG_FILE,
    put_file_to_presigned_url,
    pack_cwd_to_tar,
    read_config,
    write_api_base_url,
)

app = typer.Typer(
    help="SageCLI：云端 GPU 训练任务调度（打包 → 预签名上传 → 提交 SageMaker）",
    no_args_is_help=True,
)
console = Console()


def _get_api_url() -> str:
    try:
        cfg = read_config()
    except FileNotFoundError:
        console.print("[bold red]未找到配置文件。[/bold red]")
        console.print(f"请先运行 [bold yellow]sagecli config[/bold yellow]（将写入 {CONFIG_FILE}）。")
        raise typer.Exit(1) from None
    url = cfg.get("api_url", "").strip().rstrip("/")
    if not url:
        console.print("[bold red]配置中 api_url 为空，请重新执行 sagecli config。[/bold red]")
        raise typer.Exit(1)
    return url


@app.command("config")
def config_cmd(
    api_url: str = typer.Option(
        ...,
        prompt="请输入后端 API 地址（如 http://127.0.0.1:8000）",
        help="FastAPI 服务根地址，无末尾斜杠",
    ),
) -> None:
    """保存后端 API 基础地址到 ~/.sagecli/config.json。"""
    write_api_base_url(api_url)
    console.print(
        Panel(
            f"[green]配置已保存[/green]\nAPI: [bold]{api_url.rstrip('/')}[/bold]",
            title="sagecli",
        )
    )


@app.command("submit")
def submit_cmd(
    user: str = typer.Option(
        os.getenv("USER", "default-user"),
        "--user",
        "-u",
        help="用户标识，会用于 S3 路径与任务名",
    ),
    prefix: str = typer.Option(
        "cli-job",
        "--prefix",
        "-p",
        help="SageMaker 任务名前缀",
    ),
) -> None:
    """将当前目录打包为 code.tar.gz，经预签名上传后调用 /submit-job。"""
    api_url = _get_api_url()
    tar_name = "code.tar.gz"
    tar_path: Path | None = None

    try:
        with console.status("[cyan]正在打包当前目录…[/cyan]"):
            tar_path = pack_cwd_to_tar(tar_name)
        size_mb = tar_path.stat().st_size / (1024 * 1024)
        console.print(f"打包完成: [bold]{tar_path.name}[/bold]（{size_mb:.2f} MB）")

        with console.status("[cyan]正在请求预签名上传地址…[/cyan]"):
            r = requests.post(
                f"{api_url}/generate-upload-url",
                json={"file_name": tar_name, "user_id": user},
                timeout=60,
            )
            r.raise_for_status()
            data = r.json()
            upload_url = data["upload_url"]
            s3_uri = data["s3_uri"]

        console.print("[green]已获取上传通道[/green]，正在上传…")
        put_res = put_file_to_presigned_url(tar_path, upload_url)
        put_res.raise_for_status()
        console.print("[green]已上传到 S3[/green]")

        with console.status("[cyan]正在提交训练任务…[/cyan]"):
            sub = requests.post(
                f"{api_url}/submit-job",
                json={
                    "user_id": user,
                    "script_s3_uri": s3_uri,
                    "job_name_prefix": prefix,
                },
                timeout=120,
            )
            sub.raise_for_status()
            out = sub.json()
            job_name = out["job_name"]

        console.print(
            Panel(
                f"[bold green]任务已提交[/bold green]\n\n"
                f"用户: {user}\n"
                f"任务名: [yellow]{job_name}[/yellow]\n\n"
                f"查询状态: [cyan]sagecli status {job_name}[/cyan]",
                title="完成",
                expand=False,
            )
        )
    except HTTPError as e:
        console.print(f"[bold red]HTTP 错误:[/bold red] {e}")
        if e.response is not None:
            console.print(e.response.text)
        raise typer.Exit(1) from e
    except RequestException as e:
        console.print(f"[bold red]请求失败:[/bold red] {e}")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"[bold red]执行失败:[/bold red] {e}")
        raise typer.Exit(1) from e
    finally:
        if tar_path is not None and tar_path.is_file():
            tar_path.unlink(missing_ok=True)


@app.command("status")
def status_cmd(job_name: str = typer.Argument(..., help="submit 返回的 job_name")) -> None:
    """查询 /job-status/{job_name}。"""
    api_url = _get_api_url()
    try:
        with console.status(f"[cyan]查询 {job_name}…[/cyan]"):
            res = requests.get(f"{api_url}/job-status/{job_name}", timeout=60)
            res.raise_for_status()
            data = res.json()
    except HTTPError as e:
        console.print(f"[red]查询失败:[/red] {e}")
        if e.response is not None and e.response.status_code == 404:
            console.print("[yellow]请确认任务名是否正确。[/yellow]")
        raise typer.Exit(1) from e
    except RequestException as e:
        console.print(f"[red]请求失败:[/red] {e}")
        raise typer.Exit(1) from e

    st = data["status"]
    if st == "Completed":
        color = "green"
    elif st == "InProgress":
        color = "yellow"
    else:
        color = "red"
    console.print(
        Panel(
            f"任务: {data['job_name']}\n"
            f"状态: [bold {color}]{st}[/bold {color}]\n"
            f"细分: {data.get('secondary_status') or '—'}",
            title="任务状态",
            expand=False,
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
