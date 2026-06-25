"""
YLFile 构建脚本
自动递增版本号 + PyInstaller 打包 + Inno Setup 安装包

用法：python build.py
"""
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

APP_PY = Path(__file__).parent / "app.py"
README_MD = Path(__file__).parent / "README.md"
REDIST_DIR = Path(__file__).parent / "redist"
VC_REDIST = REDIST_DIR / "vc_redist.x64.exe"
VC_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"

# Inno Setup 路径（默认安装位置）
ISCC_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


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
    text = APP_PY.read_text(encoding="utf-8")
    text = text.replace(f'__version__ = "{old}"', f'__version__ = "{new}"')
    text = text.replace(f"YLFile v{old}", f"YLFile v{new}")
    APP_PY.write_text(text, encoding="utf-8")
    print(f"[OK] app.py: v{old} -> v{new}")

    if README_MD.exists():
        text = README_MD.read_text(encoding="utf-8")
        text = text.replace(f"v{old}", f"v{new}")
        README_MD.write_text(text, encoding="utf-8")
        print(f"[OK] README.md: v{old} -> v{new}")


def ensure_vc_redist():
    """确保 VC++ 运行时安装包存在"""
    if VC_REDIST.exists():
        print(f"[OK] VC++ 运行时已存在: {VC_REDIST}")
        return
    REDIST_DIR.mkdir(exist_ok=True)
    print(f"[下载] VC++ 运行时 ({VC_URL})...")
    try:
        urllib.request.urlretrieve(VC_URL, str(VC_REDIST))
        print(f"[OK] VC++ 运行时下载完成: {VC_REDIST.stat().st_size // 1024 // 1024}MB")
    except Exception as e:
        print(f"[警告] VC++ 运行时下载失败: {e}")
        print("  安装包将不包含 VC++ 运行时，用户可能需要手动安装")


def build_exe():
    """调用 PyInstaller 打包 exe"""
    hidden = [
        "selenium", "selenium.webdriver", "selenium.webdriver.common",
        "selenium.webdriver.common.by", "selenium.webdriver.common.keys",
        "selenium.webdriver.common.action_chains", "selenium.webdriver.common.service",
        "selenium.webdriver.chrome", "selenium.webdriver.chrome.webdriver",
        "selenium.webdriver.chrome.options", "selenium.webdriver.chrome.service",
        "selenium.webdriver.remote", "selenium.webdriver.remote.webdriver",
        "selenium.webdriver.remote.webelement", "selenium.webdriver.remote.command",
        "selenium.webdriver.support", "selenium.webdriver.support.ui",
        "selenium.webdriver.support.expected_conditions",
        "openai", "requests", "urllib3",
    ]
    cmd = [sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole", "--name=YLFile"]
    for h in hidden:
        cmd.extend(["--hidden-import", h])
    cmd.append("main.py")
    print(f"\n[构建] PyInstaller 打包中...\n")
    ret = subprocess.run(cmd, cwd=str(Path(__file__).parent))
    if ret.returncode == 0:
        print(f"\n[OK] YLFile.exe 构建完成")
    else:
        print(f"\n[失败] PyInstaller 返回码: {ret.returncode}")
        sys.exit(ret.returncode)


def build_installer(version: str):
    """调用 Inno Setup 编译安装包"""
    iscc = None
    for p in ISCC_PATHS:
        if Path(p).exists():
            iscc = p
            break
    if not iscc:
        print("[跳过] 未找到 Inno Setup，跳过安装包构建")
        print("  安装 Inno Setup: https://jrsoftware.org/isinfo.php")
        return

    # 更新 installer.iss 中的版本号
    iss_path = Path(__file__).parent / "installer.iss"
    if iss_path.exists():
        text = iss_path.read_text(encoding="utf-8")
        text = re.sub(r'#define MyAppVersion ".*"', f'#define MyAppVersion "{version}"', text)
        iss_path.write_text(text, encoding="utf-8")

    print(f"\n[构建] Inno Setup 编译安装包...\n")
    ret = subprocess.run([iscc, str(iss_path)], cwd=str(Path(__file__).parent))
    if ret.returncode == 0:
        setup_path = Path(__file__).parent / "dist" / "YLFile-Setup.exe"
        if setup_path.exists():
            print(f"[OK] YLFile-Setup.exe 构建完成 ({setup_path.stat().st_size // 1024 // 1024}MB)")
        else:
            print("[警告] 安装包构建完成但未找到输出文件")
    else:
        print(f"[失败] Inno Setup 返回码: {ret.returncode}")


if __name__ == "__main__":
    old_ver = read_version()
    new_ver = bump_version(old_ver)
    print(f"版本号: v{old_ver} -> v{new_ver}\n")

    update_version(old_ver, new_ver)
    ensure_vc_redist()
    build_exe()
    build_installer(new_ver)

    print(f"\n{'='*50}")
    print(f"构建完成! 输出目录: dist/")
    print(f"  YLFile.exe      - 主程序")
    print(f"  YLFile-Setup.exe - 安装包")
    print(f"{'='*50}")
