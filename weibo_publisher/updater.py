"""
YLFile 自动更新模块
通过 GitHub Releases 检查新版本，下载安装包并静默安装。
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
SETUP_ASSET = "YLFile-Setup.exe"  # 安装包文件名
EXE_ASSET = "YLFile.exe"  # 兜底：如果没有安装包就下载 exe


def _parse_version(ver_str: str):
    """将 '4.2' 或 'v4.2' 解析为 (major, minor) 元组"""
    ver = ver_str.strip().lstrip("vV")
    parts = ver.split(".")
    try:
        return tuple(int(p) for p in parts[:2])
    except (ValueError, IndexError):
        return (0, 0)


def _get_token():
    """从 config.json 读取 GitHub token"""
    try:
        cfg_path = Path(__file__).parent / "config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text("utf-8"))
            return cfg.get("github_token", "")
    except Exception:
        pass
    return ""


def check_update(current_version: str):
    """
    检查 GitHub 最新 Release 是否有新版本。

    Returns:
        (has_update, new_version, download_url, is_installer) 有更新时返回
        None  网络异常或无更新
    """
    try:
        headers = {"Accept": "application/vnd.github+json"}
        token = _get_token()
        if token:
            headers["Authorization"] = f"token {token}"

        resp = requests.get(GITHUB_API, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        tag = data.get("tag_name", "")
        if not tag:
            return None

        new_ver = tag.lstrip("vV")
        cur_ver = current_version.strip().lstrip("vV")

        if _parse_version(new_ver) <= _parse_version(cur_ver):
            logger.info(f"当前已是最新版本: {cur_ver}")
            return None

        # 优先找安装包，兜底找 exe
        download_url = None
        is_installer = False
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name == SETUP_ASSET:
                download_url = asset.get("browser_download_url")
                is_installer = True
                break
            elif name == EXE_ASSET and not download_url:
                download_url = asset.get("browser_download_url")

        if not download_url:
            logger.warning(f"新版本 {new_ver} 未找到下载链接")
            return None

        logger.info(f"发现新版本: {new_ver}（当前 {cur_ver}）")
        return (True, new_ver, download_url, is_installer)

    except Exception as e:
        logger.info(f"检查更新跳过: {e}")
        return None


def download_update(url: str, dest_dir: Path, filename: str = "YLFile_update.exe", progress_cb=None) -> Path | None:
    """
    下载更新文件到 dest_dir/filename。
    progress_cb(percent) 会被回调，percent 为 0-100。
    """
    dest = dest_dir / filename
    try:
        logger.info(f"开始下载更新: {url}")
        resp = requests.get(url, stream=True, timeout=600)
        resp.raise_for_status()

        total = int(resp.headers.get("content-length", 0))
        downloaded = 0

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and progress_cb:
                    pct = downloaded * 100 // total
                    progress_cb(pct)

        logger.info(f"下载完成: {dest} ({downloaded // 1024 // 1024}MB)")
        return dest

    except Exception as e:
        logger.error(f"下载更新失败: {e}")
        if dest.exists():
            dest.unlink()
        return None


def install_update(installer_path: Path, is_installer: bool = True):
    """
    运行安装包或替换 exe，然后退出当前进程。

    is_installer=True: 运行 Inno Setup 安装包（静默模式）
    is_installer=False: 直接替换 exe（兼容旧版）
    """
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

    if is_installer:
        # 运行安装包：/SILENT 静默安装，/DIR 指定目录，/RESTARTAPPLICATIONS 安装后重启
        cmd = [
            str(installer_path),
            "/SILENT",
            f"/DIR={exe_dir}",
            "/RESTARTAPPLICATIONS",
        ]
        logger.info(f"启动安装包: {' '.join(cmd)}")
    else:
        # 兜底：用 bat 脚本替换 exe
        bat_path = exe_dir / "temp" / "restart.bat"
        bat_path.parent.mkdir(exist_ok=True)
        bat_content = f"""@echo off
timeout /t 2 /nobreak >nul
move /y "{installer_path}" "{exe_dir}\\YLFile.exe"
start "" "{exe_dir}\\YLFile.exe"
del "%~f0"
"""
        bat_path.write_text(bat_content, encoding="gbk")
        cmd = ["cmd", "/c", str(bat_path)]
        logger.info(f"启动替换脚本: {bat_path}")

    # 启动安装/替换进程
    subprocess.Popen(
        cmd,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
    )
    time.sleep(0.5)
    os._exit(0)
