"""
上传 YLFile自动发布 到 GitHub Release
用法: python upload_release.py <github_token>
"""
import sys
import json
import time
import requests
from pathlib import Path

REPO = "ylfile/DramaWeibo"
TAG = "v4.12"
DIST_DIR = Path(__file__).parent / "dist"
ASSETS = [
    ("YLFile-Setup.exe", DIST_DIR / "YLFile-Setup.exe"),
]


def upload_asset(api, headers, release_id, asset_name, asset_path):
    """上传一个文件到 release，如果已存在则先删除"""
    if not asset_path.exists():
        print(f"  [跳过] {asset_name} 不存在")
        return True

    # 先删除已存在的同名文件
    r = requests.get(f"{api}/releases/{release_id}/assets", headers=headers)
    if r.status_code == 200:
        for a in r.json():
            if a.get("name") == asset_name:
                print(f"  删除旧版 {asset_name}...")
                requests.delete(a["url"], headers=headers)

    size = asset_path.stat().st_size
    print(f"  上传 {asset_name} ({size // 1024 // 1024}MB)...")
    url = f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name={asset_name}"
    # 绕过系统代理上传（代理对大文件上传不稳定）
    proxy_bypass = {"http": None, "https": None}
    for attempt in range(1, 4):
        try:
            with open(asset_path, "rb") as f:
                r = requests.post(
                    url,
                    headers={**headers, "Content-Type": "application/octet-stream"},
                    data=f,
                    timeout=(10, 600),
                    proxies=proxy_bypass,
                )
            if r.status_code in (200, 201):
                print(f"  上传成功!")
                return True
            print(f"  上传失败 (第{attempt}次): {r.status_code}")
        except Exception as e:
            print(f"  上传异常 (第{attempt}次): {e}")
        if attempt < 3:
            print(f"  3秒后重试...")
            time.sleep(3)
    return False


def main():
    if len(sys.argv) < 2:
        print("用法: python upload_release.py <github_token>")
        print("  token 需要有 repo 权限")
        print("  获取: https://github.com/settings/tokens/new?scopes=repo")
        sys.exit(1)

    token = sys.argv[1]
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    api = f"https://api.github.com/repos/{REPO}"

    # 1. 检查 tag
    print(f"[1/4] 检查 tag {TAG}...")
    r = requests.get(f"{api}/git/ref/tags/{TAG}", headers=headers, allow_redirects=True)
    if r.status_code != 200:
        print(f"  Tag {TAG} 不存在，先创建...")
        r2 = requests.get(f"{api}/commits/master", headers=headers)
        sha = r2.json()["sha"]
        r3 = requests.post(f"{api}/git/refs", headers=headers, json={
            "ref": f"refs/tags/{TAG}", "sha": sha,
        })
        if r3.status_code not in (200, 201):
            print(f"  创建 tag 失败: {r3.status_code} {r3.text}")
            sys.exit(1)
    print(f"  Tag {TAG} 就绪")

    # 2. 检查 Release
    print(f"[2/4] 检查 Release...")
    r = requests.get(f"{api}/releases/tags/{TAG}", headers=headers)
    if r.status_code == 200:
        release_id = r.json()["id"]
        print(f"  Release 已存在 (id={release_id})")
    else:
        r = requests.post(f"{api}/releases", headers=headers, json={
            "tag_name": TAG,
            "name": f"YLFile自动发布 {TAG}",
            "body": "## YLFile自动发布 v4.12\n\n"
                    "### 修复\n"
                    "- 起始行手动输入不生效：启动时不再用上次保存的值覆盖\n"
                    "- 下载更新支持国内镜像加速和断点续传\n\n"
                    "### 安装包\n"
                    "- 下载 `YLFile-Setup.exe` 安装（推荐）",
            "draft": False,
            "prerelease": False,
        })
        if r.status_code not in (200, 201):
            print(f"  创建 Release 失败: {r.text}")
            sys.exit(1)
        release_id = r.json()["id"]
        print(f"  Release 创建成功 (id={release_id})")

    # 3. 上传文件
    print(f"[3/4] 上传文件...")
    for name, path in ASSETS:
        upload_asset(api, headers, release_id, name, path)

    # 4. 验证
    print(f"[4/4] 验证...")
    r = requests.get(f"{api}/releases/tags/{TAG}", headers=headers)
    assets = r.json().get("assets", [])
    for a in assets:
        print(f"  [OK] {a['name']} ({a['size'] // 1024 // 1024}MB)")
    print(f"\n[DONE] https://github.com/{REPO}/releases/tag/{TAG}")


if __name__ == "__main__":
    main()
