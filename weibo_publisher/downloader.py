"""
海报下载模块
负责从URL下载海报图片到本地temp文件夹，以及清理临时文件
"""

import os
import time
import requests
from pathlib import Path


def get_temp_folder() -> Path:
    """
    获取临时文件夹路径，不存在则自动创建

    Returns:
        Path对象，指向temp文件夹
    """
    # 读取配置中的temp_folder路径
    import json
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    temp_dir = Path(__file__).parent / config["temp_folder"]
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def download_poster(url: str, drama_name: str) -> str:
    """
    从URL下载海报图片到本地temp文件夹

    Args:
        url: 海报图片URL（通常是豆瓣图片链接）
        drama_name: 剧名，用于命名本地文件

    Returns:
        下载后的本地文件完整路径

    Raises:
        Exception: 下载失败时抛出异常
    """
    temp_dir = get_temp_folder()

    # 根据URL推断文件扩展名，默认.jpg
    ext = ".jpg"
    if ".png" in url.lower():
        ext = ".png"
    elif ".webp" in url.lower():
        ext = ".webp"

    # 生成本地文件名：剧名+时间戳，避免重名
    timestamp = int(time.time() * 1000)
    # 清理剧名中的特殊字符
    safe_name = drama_name.replace(" ", "_").replace("/", "_").replace("\\", "_")
    filename = f"{safe_name}_{timestamp}{ext}"
    filepath = temp_dir / filename

    # 设置请求头，添加Referer防止豆瓣防盗链
    headers = {
        "Referer": "https://movie.douban.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    # 下载图片，超时30秒
    response = requests.get(url, headers=headers, timeout=30, stream=True)
    response.raise_for_status()  # 状态码非200时抛出异常

    # 写入本地文件
    with open(filepath, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    # 验证文件大小
    file_size = os.path.getsize(filepath)
    if file_size < 1024:  # 小于1KB，可能下载失败或返回了错误页面
        os.remove(filepath)
        raise Exception(f"下载的图片文件过小（{file_size}字节），可能URL无效或被防盗链拦截")

    return str(filepath)


def cleanup_temp(drama_name: str = None):
    """
    清理temp文件夹中的临时图片

    Args:
        drama_name: 如果指定，只清理该剧名相关的文件；否则清理全部
    """
    temp_dir = get_temp_folder()

    for file in temp_dir.iterdir():
        if file.is_file():
            # 清理所有图片文件
            if file.suffix.lower() in (".jpg", ".png", ".webp", ".jpeg", ".gif"):
                if drama_name is None:
                    # 清理全部
                    try:
                        file.unlink()
                    except OSError:
                        pass  # 文件被占用时忽略
                elif drama_name and drama_name in file.name:
                    try:
                        file.unlink()
                    except OSError:
                        pass


# 本地测试用
if __name__ == "__main__":
    test_url = "https://img2.doubanio.com/view/photo/s_ratio_poster/public/p2561439800.webp"
    path = download_poster(test_url, "测试剧")
    print(f"下载完成：{path}")
    cleanup_temp("测试剧")
    print("清理完成")
