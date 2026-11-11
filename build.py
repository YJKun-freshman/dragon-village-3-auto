# -*- coding: utf-8 -*-
"""
打包（在 Windows 上執行，雙擊 打包.bat）：
  dist\\dragon-village-3-auto_v版本_exe.zip      exe 版（PyInstaller --onedir，免裝 Python）
  dist\\dragon-village-3-auto_v版本_python.zip   Python 原始碼版
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from app import APP_NAME, __version__  # noqa: E402

EXE_NAME = "龍村3自動腳本"
ZIP_NAME = "dragon-village-3-auto"     # GitHub 附件檔名不能有中文（會被刪掉），zip 用英文
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")

# 兩個版本都要附的檔案
DOCS = ["README.md", "LICENSE"]
# Python 版的內容
PY_ITEMS = ["app", "core", "ui", "combat", "fishing", "main.py", "requirements.txt",
            "啟動.bat", "capture.bat"] + DOCS
SKIP_DIRS = {"__pycache__"}
# 有資料檔（樣板圖）的資料夾：exe 版要一起帶
DATA_DIRS = ["core/templates", "fishing/templates", "combat/templates"]
# 會用 importlib 動態載入的模組，PyInstaller 自己找不到
PACKAGES = ["app", "core", "ui", "combat", "fishing"]


def run(cmd):
    print(">", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("第一次打包，安裝 PyInstaller……")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])


def zip_dir(src, zip_path, arc_root):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, files in os.walk(src):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for f in files:
                full = os.path.join(dirpath, f)
                z.write(full, os.path.join(arc_root, os.path.relpath(full, src)))


def build_exe():
    ensure_pyinstaller()
    sep = ";" if os.name == "nt" else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "main.py",
           "--name", EXE_NAME, "--onedir", "--windowed", "--noconfirm", "--clean",
           "--distpath", DIST, "--workpath", BUILD, "--specpath", BUILD,
           "--collect-data", "customtkinter",
           "--exclude-module", "ui.demo"]
    for d in DATA_DIRS:
        cmd += ["--add-data", f"{os.path.join(ROOT, d)}{sep}{d}"]
    for p in PACKAGES:
        cmd += ["--collect-submodules", p]
    run(cmd)
    out = os.path.join(DIST, EXE_NAME)
    for f in DOCS:
        shutil.copy2(os.path.join(ROOT, f), out)
    z = os.path.join(DIST, f"{ZIP_NAME}_v{__version__}_exe.zip")
    zip_dir(out, z, EXE_NAME)
    return z


def build_python():
    z = os.path.join(DIST, f"{ZIP_NAME}_v{__version__}_python.zip")
    arc = f"{EXE_NAME}_v{__version__}"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in PY_ITEMS:
            src = os.path.join(ROOT, item)
            if os.path.isdir(src):
                for dirpath, dirnames, files in os.walk(src):
                    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
                    for f in files:
                        full = os.path.join(dirpath, f)
                        zf.write(full, os.path.join(arc, os.path.relpath(full, ROOT)))
            elif os.path.exists(src):
                zf.write(src, os.path.join(arc, item))
            else:
                print(f"⚠ 找不到 {item}，略過")
    return z


def main():
    print(f"=== {APP_NAME} v{__version__} 打包 ===")
    os.makedirs(DIST, exist_ok=True)
    py_zip = build_python()
    exe_zip = build_exe()
    print("\n完成！")
    print(" exe 版：", exe_zip)
    print(" Python 版：", py_zip)
    print(" exe 可以直接試：", os.path.join(DIST, EXE_NAME, EXE_NAME + ".exe"))


if __name__ == "__main__":
    main()
