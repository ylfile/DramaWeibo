# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['selenium', 'selenium.webdriver', 'selenium.webdriver.common', 'selenium.webdriver.common.by', 'selenium.webdriver.common.keys', 'selenium.webdriver.common.action_chains', 'selenium.webdriver.common.service', 'selenium.webdriver.chrome', 'selenium.webdriver.chrome.webdriver', 'selenium.webdriver.chrome.options', 'selenium.webdriver.chrome.service', 'selenium.webdriver.remote', 'selenium.webdriver.remote.webdriver', 'selenium.webdriver.remote.webelement', 'selenium.webdriver.remote.command', 'selenium.webdriver.support', 'selenium.webdriver.support.ui', 'selenium.webdriver.support.expected_conditions', 'openai', 'requests', 'urllib3'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='YLFile',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
