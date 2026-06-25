"""
YLFile 构建脚本
自动递增版本号 + PyInstaller 打包

用法：python build.py
"""
import re
import subprocess
import sys
from pathlib import Path

APP_PY = Path(__file__).parent / "app.py"
README_MD = Path(__file__).parent / "README.md"


def read_version():
    """从 app.py 读取当前 __version__"""
    text = APP_PY.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\'](\d+\.\d+)["\']', text)
    if not m:
        print("[错误] 无法从 app.py 中读取版本号")
        sys.exit(1)
    return m.group(1)


def bump_version(version: str):
    """将 minor 版本号 +1，如 4.2 → 4.3"""
    major, minor = version.split(".")
    return f"{major}.{int(minor) + 1}"


def update_version(old: str, new: str):
    """更新 app.py 和 README.md 中的版本号"""
    # 更新 app.py 中的 __version__
    text = APP_PY.read_text(encoding="utf-8")
    text = text.replace(f'__version__ = "{old}"', f'__version__ = "{new}"')
    text = text.replace(f"YLFile v{old}", f"YLFile v{new}")
    APP_PY.write_text(text, encoding="utf-8")
    print(f"[OK] app.py: v{old} → v{new}")

    # 更新 README.md
    if README_MD.exists():
        text = README_MD.read_text(encoding="utf-8")
        text = text.replace(f"v{old}", f"v{new}")
        README_MD.write_text(text, encoding="utf-8")
        print(f"[OK] README.md: v{old} → v{new}")


def build():
    """调用 PyInstaller 打包"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--noconsole",
        "--name=YLFile",
        "main.py",
    ]
    print(f"\n[构建] {' '.join(cmd)}\n")
    ret = subprocess.run(cmd, cwd=str(Path(__file__).parent))
    if ret.returncode == 0:
        print("\n[成功] 构建完成！输出: dist/YLFile.exe")
    else:
        print(f"\n[失败] PyInstaller 返回码: {ret.returncode}")
        sys.exit(ret.returncode)


if __name__ == "__main__":
    old_ver = read_version()
    new_ver = bump_version(old_ver)
    print(f"版本号: v{old_ver} → v{new_ver}\n")

    update_version(old_ver, new_ver)
    build()
