"""
YLFile 自动更新模块
通过 GitHub Releases 检查新版本，下载并重启替换。
"""
import os
import sys
import json
import subprocess
import time
import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

GITHUB_REPO = "ylfile/DramaWeibo"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_NAME = "YLFile.exe"  # Release 中上传的 exe 文件名


def _parse_version(ver_str: str):
    """将 '4.2' 或 'v4.2' 解析为 (major, minor) 元组"""
    ver = ver_str.strip().lstrip("vV")
    parts = ver.split(".")
    try:
        return tuple(int(p) for p in parts[:2])
    except (ValueError, IndexError):
        return (0, 0)


def check_update(current_version: str):
    """
    检查 GitHub 最新 Release 是否有新版本。

    Returns:
        (has_update, new_version, download_url) 有更新时返回
        None  网络异常或无更新
    """
    try:
        headers = {"Accept": "application/vnd.github+json"}
        # 如果 config 中有 GitHub token 则使用，提高 API 限额（5000次/小时）
        try:
            cfg = json.loads(Path(__file__).parent.joinpath("config.json").read_text("utf-8"))
            token = cfg.get("github_token", "")
            if token:
                headers["Authorization"] = f"token {token}"
        except Exception:
            pass
        resp = requests.get(GITHUB_API, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        tag = data.get("tag_name", "")  # e.g. "v4.3"
        if not tag:
            return None

        new_ver = tag.lstrip("vV")
        cur_ver = current_version.strip().lstrip("vV")

        if _parse_version(new_ver) <= _parse_version(cur_ver):
            logger.info(f"当前已是最新版本: {cur_ver}")
            return None

        # 从 assets 中找 exe 下载链接
        download_url = None
        for asset in data.get("assets", []):
            if asset.get("name", "") == ASSET_NAME:
                download_url = asset.get("browser_download_url")
                break

        if not download_url:
            logger.warning(f"新版本 {new_ver} 未找到 {ASSET_NAME} 下载链接")
            return None

        logger.info(f"发现新版本: {new_ver}（当前 {cur_ver}）")
        return (True, new_ver, download_url)

    except Exception as e:
        logger.info(f"检查更新跳过: {e}")
        return None


def download_update(url: str, dest_dir: Path) -> Path | None:
    """
    下载新版本 exe 到 dest_dir/YLFile_new.exe。

    Returns:
        下载完成的文件路径，失败返回 None
    """
    dest = dest_dir / "YLFile_new.exe"
    try:
        logger.info(f"开始下载更新: {url}")
        resp = requests.get(url, stream=True, timeout=300)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = downloaded * 100 // total
                    logger.info(f"下载进度: {pct}% ({downloaded // 1024}KB / {total // 1024}KB)")

        logger.info(f"下载完成: {dest} ({downloaded // 1024}KB)")
        return dest

    except Exception as e:
        logger.error(f"下载更新失败: {e}")
        if dest.exists():
            dest.unlink()
        return None


def restart_app(new_exe_path: Path):
    """
    生成 restart.bat 脚本，等待当前进程退出后替换 exe 并重启。
    """
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    bat_path = exe_dir / "temp" / "restart.bat"

    # 确保 temp 目录存在
    bat_path.parent.mkdir(exist_ok=True)

    bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
move /y "{new_exe_path}" "{exe_dir}\\YLFile.exe"
start "" "{exe_dir}\\YLFile.exe"
del "%~f0"
"""
    bat_path.write_text(bat_content, encoding="gbk")
    logger.info(f"重启脚本已生成: {bat_path}")

    # 启动 bat 脚本，然后退出当前进程
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(0.5)
    os._exit(0)
