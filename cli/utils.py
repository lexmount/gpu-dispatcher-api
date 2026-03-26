"""打包目录、HTTP 上传（含进度）。"""

from __future__ import annotations

import json
import os
import tarfile
from pathlib import Path

import requests
from rich.progress import BarColumn, Progress, TaskID, TextColumn, TransferSpeedColumn

# 打包时忽略的目录（避免把本地环境传到云端）
IGNORE_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
    }
)

CONFIG_DIR = Path.home() / ".sagecli"
CONFIG_FILE = CONFIG_DIR / "config.json"


def read_config() -> dict:
    if not CONFIG_FILE.is_file():
        raise FileNotFoundError(str(CONFIG_FILE))
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def write_api_base_url(api_url: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    api_url = api_url.rstrip("/")
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"api_url": api_url}, f, indent=2)


def pack_cwd_to_tar(
    archive_name: str = "code.tar.gz",
    *,
    cwd: str | None = None,
) -> Path:
    """
    将当前工作目录（默认 os.getcwd()）打成 tar.gz，归档文件位于该目录下。
    会忽略 IGNORE_DIRS，且不将生成的 archive 自身再次打入包内。
    """
    base = Path(cwd or os.getcwd()).resolve()
    out_path = base / archive_name
    if out_path.exists():
        out_path.unlink()

    with tarfile.open(out_path, "w:gz") as tar:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for name in files:
                if name == archive_name:
                    continue
                file_path = Path(root) / name
                arcname = file_path.relative_to(base)
                tar.add(file_path, arcname=str(arcname))

    return out_path


class _ProgressFileReader:
    """供 requests 流式读取，并在 read 时更新 Rich 进度。"""

    def __init__(self, path: Path, progress: Progress, task_id: TaskID) -> None:
        self._path = path
        self._f = path.open("rb")
        self._progress = progress
        self._task_id = task_id
        self._total = path.stat().st_size

    def __len__(self) -> int:
        return self._total

    def read(self, n: int = -1) -> bytes:
        chunk_size = 256 * 1024 if n is None or n < 0 else n
        chunk = self._f.read(chunk_size)
        if chunk:
            self._progress.update(self._task_id, advance=len(chunk))
        return chunk

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> _ProgressFileReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def put_file_to_presigned_url(file_path: Path, upload_url: str) -> requests.Response:
    """
    使用 PUT 将本地文件上传到预签名 URL，并显示上传进度与速度。
    设置 Content-Length 以兼容常见 S3 预签名 PUT 要求。
    """
    total = file_path.stat().st_size
    headers = {"Content-Length": str(total)}

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TransferSpeedColumn(),
        TextColumn("{task.completed}/{task.total} bytes"),
    ) as progress:
        task_id = progress.add_task("上传到 S3", total=total)
        with _ProgressFileReader(file_path, progress, task_id) as body:
            return requests.put(upload_url, data=body, headers=headers, timeout=3600)
