"""
上传 YLFile.exe 到 GitHub Release
用法: python upload_release.py <github_token>
"""
import sys
import json
import requests
from pathlib import Path

REPO = "ylfile/DramaWeibo"
TAG = "v4.3"
EXE = Path(__file__).parent / "dist" / "YLFile.exe"


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

    # 1. 检查 tag 是否存在
    print(f"[1/4] 检查 tag {TAG}...")
    r = requests.get(f"{api}/git/ref/tags/{TAG}", headers=headers, allow_redirects=True)
    if r.status_code != 200:
        print(f"  Tag {TAG} 不存在，先创建...")
        # 用 SHA 原始方式创建 annotated tag
        r2 = requests.get(f"{api}/commits/master", headers=headers)
        sha = r2.json()["sha"]
        r3 = requests.post(f"{api}/git/refs", headers=headers, json={
            "ref": f"refs/tags/{TAG}",
            "sha": sha,
        })
        if r3.status_code not in (200, 201):
            print(f"  创建 tag 失败: {r3.status_code} {r3.text}")
            sys.exit(1)
    print(f"  Tag {TAG} 就绪")

    # 2. 检查是否已有 release
    print(f"[2/4] 检查 Release...")
    r = requests.get(f"{api}/releases/tags/{TAG}", headers=headers)
    if r.status_code == 200:
        release_id = r.json()["id"]
        print(f"  Release 已存在 (id={release_id})")
    else:
        # 创建 release
        r = requests.post(f"{api}/releases", headers=headers, json={
            "tag_name": TAG,
            "name": f"YLFile {TAG}",
            "body": "## YLFile v4.3 更新内容\n\n"
                    "### 新功能\n"
                    "- **自动更新**：启动时自动检查 GitHub 新版本，有新版弹窗提示，一键下载替换重启\n"
                    "- **评论模板变量**：评论区现在支持所有变量\n\n"
                    "### 从旧版本升级\n"
                    "直接下载 YLFile.exe 替换即可，config.json 和 memory.json 不受影响。",
            "draft": False,
            "prerelease": False,
        })
        if r.status_code not in (200, 201):
            print(f"  创建 Release 失败: {r.text}")
            sys.exit(1)
        release_id = r.json()["id"]
        print(f"  Release 创建成功 (id={release_id})")

    # 3. 上传 exe
    print(f"[3/4] 上传 {EXE.name} ({EXE.stat().st_size // 1024 // 1024}MB)...")
    upload_url = f"https://uploads.github.com/repos/{REPO}/releases/{release_id}/assets?name=YLFile.exe"

    with open(EXE, "rb") as f:
        r = requests.post(
            upload_url,
            headers={**headers, "Content-Type": "application/octet-stream"},
            data=f,
        )

    if r.status_code not in (200, 201):
        print(f"  上传失败: {r.text}")
        sys.exit(1)
    print(f"  上传成功!")

    # 4. 验证
    print(f"[4/4] 验证...")
    r = requests.get(f"{api}/releases/tags/{TAG}", headers=headers)
    assets = r.json().get("assets", [])
    for a in assets:
        print(f"  [OK] {a['name']} ({a['size'] // 1024 // 1024}MB)")
    print(f"\n🎉 完成! Release 地址: https://github.com/{REPO}/releases/tag/{TAG}")


if __name__ == "__main__":
    main()
