"""
YLFile自动发布 自动更新模块
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

        # 先尝试系统代理，失败后绕过
        resp = None
        for proxies in [None, {"http": None, "https": None}]:
            try:
                resp = requests.get(GITHUB_API, headers=headers, timeout=15, proxies=proxies)
                resp.raise_for_status()
                break
            except Exception:
                resp = None
                continue
        if resp is None:
            logger.warning("GitHub API 请求失败（代理和直连均失败）")
            return None
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


def _get_download_urls(github_url: str):
    """返回下载URL列表：国内镜像优先，GitHub直连兜底"""
    return [
        f"https://mirror.ghproxy.com/{github_url}",
        f"https://ghfast.top/{github_url}",
        github_url,
    ]


def download_update(url: str, dest_dir: Path, filename: str = "YLFile_update.exe", progress_cb=None) -> Path | None:
    """
    下载更新文件到 dest_dir/filename，国内镜像加速 + 断点续传。
    先尝试系统代理，失败后绕过代理直连。
    progress_cb(percent) 会被回调，percent 为 0-100。
    """
    dest = dest_dir / filename
    urls = _get_download_urls(url)

    # 第一轮：用系统代理（默认行为）
    for mirror_url in urls:
        logger.info(f"尝试下载（代理）: {mirror_url[:80]}...")
        result = _try_download(mirror_url, dest, progress_cb, use_proxy=True)
        if result:
            return result
        logger.warning(f"代理下载失败，尝试直连...")

    # 第二轮：绕过代理直连
    for mirror_url in urls:
        logger.info(f"尝试下载（直连）: {mirror_url[:80]}...")
        result = _try_download(mirror_url, dest, progress_cb, use_proxy=False)
        if result:
            return result

    logger.error("所有下载源均失败")
    if dest.exists():
        dest.unlink()
    return None


def _try_download(url, dest, progress_cb, use_proxy=True, max_retries=3):
    """单个URL的下载逻辑，支持断点续传和重试"""
    proxy_setting = None if use_proxy else {"http": None, "https": None}
    for attempt in range(1, max_retries + 1):
        try:
            downloaded = dest.stat().st_size if dest.exists() else 0
            headers = {"User-Agent": "YLFile-AutoUpdater"}
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"
                logger.info(f"断点续传: 已下载 {downloaded // 1024 // 1024}MB")

            resp = requests.get(url, stream=True, timeout=(10, 30),
                                headers=headers, proxies=proxy_setting)

            if resp.status_code == 200:
                downloaded = 0  # 不支持续传，从头开始
            elif resp.status_code == 206:
                pass  # 续传成功
            else:
                resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))
            if resp.status_code == 206:
                total = downloaded + total

            with open(dest, "ab" if resp.status_code == 206 else "wb") as f:
                last_pct = (downloaded * 100 // total) if total > 0 else 0
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0 and progress_cb:
                        pct = downloaded * 100 // total
                        if pct > last_pct:
                            last_pct = pct
                            progress_cb(pct)

            logger.info(f"下载完成: {dest} ({downloaded // 1024 // 1024}MB)")
            return dest

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            logger.warning(f"下载中断 (第{attempt}次): {e}")
            if attempt < max_retries:
                time.sleep(attempt * 2)

        except Exception as e:
            logger.error(f"下载失败: {e}")
            break

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
