"""Make a portable copy of Badeel that runs on another Windows computer
without installing Python or anything else (for example the TA's laptop).

Run it on a Windows computer where start_windows.bat already works, by
double-clicking make_portable_windows.bat. It creates a folder called
Badeel_Portable next to the project folder:

    Badeel_Portable/
        Start_Badeel.bat   double-click this on the other computer
        Open_Terminal.bat  a command window for peek-users, security_check ...
        python/            the official "embeddable" Python from python.org
        libs/              Flask, scikit-learn, cryptography ... copied from .venv
        app/               the project, including instance/ (database, keys, model)

Copy that folder to a USB stick. On the other computer, copy it to the
Desktop and double-click Start_Badeel.bat. Delete it from that computer
afterwards: instance/ holds the encryption key and the demo accounts.
"""
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import sysconfig
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEST = "--test" in sys.argv  # used only to check this script on Linux
OUT = pathlib.Path(os.environ.get("BADEEL_PORTABLE_OUT", ROOT.parent / "Badeel_Portable"))

SKIP_APP = {".venv", "venv", "__pycache__", ".git", ".idea", ".vscode", OUT.name}
SKIP_LIBS = {"pip", "setuptools", "_distutils_hack", "pkg_resources", "wheel"}

START_BAT = "\r\n".join([
    "@echo off",
    "title Badeel",
    'cd /d "%~dp0app"',
    'if not exist "%~dp0python\\python.exe" (',
    "  echo  [!] Copy the whole Badeel_Portable folder, not only this file.",
    "  pause",
    "  exit /b 1",
    ")",
    'set "BADEEL_OPEN_BROWSER=1"',
    '"%~dp0python\\python.exe" run.py',
    "echo.",
    "echo The site has stopped.",
    "pause",
    "",
])


TERMINAL_BAT = "\r\n".join([
    "@echo off",
    "title Badeel - commands",
    'cd /d "%~dp0app"',
    'set "PATH=%~dp0python;%PATH%"',
    "echo.",
    "echo  Commands you can type here (the site can stay open in the other window):",
    "echo    python manage.py peek-users",
    "echo    python checks\\security_check.py",
    "echo    python ml\\evaluate.py",
    "echo.",
    "cmd /k",
    "",
])


def step(msg):
    print(f"\n== {msg}")


def get_python(dest):
    ver = platform.python_version()
    arch = {"AMD64": "amd64", "ARM64": "arm64", "x86": "win32"}.get(platform.machine(), "amd64")
    name = f"python-{ver}-embed-{arch}.zip"
    url = f"https://www.python.org/ftp/python/{ver}/{name}"
    local = ROOT / name
    if not local.exists():
        print(f"   downloading {url}")
        try:
            with urllib.request.urlopen(url, timeout=60) as r, open(local, "wb") as f:
                shutil.copyfileobj(r, f)
        except Exception as e:  # no internet, proxy, ...
            local.unlink(missing_ok=True)
            sys.exit(f"\n[!] Could not download Python ({e}).\n"
                     f"    Open this link in the browser, save the file into the project folder\n"
                     f"    ({ROOT}), then run make_portable_windows.bat again:\n    {url}")
    with zipfile.ZipFile(local) as z:
        z.extractall(dest)
    tag = f"{sys.version_info[0]}{sys.version_info[1]}"
    # The ._pth file is the embeddable Python's whole search path.
    (dest / f"python{tag}._pth").write_text(
        f"python{tag}.zip\r\n.\r\n..\\app\r\n..\\libs\r\nimport site\r\n", encoding="ascii")
    print(f"   Python {ver} ({arch}) ready")


def copy_libs(dest):
    site = pathlib.Path(sysconfig.get_paths()["purelib"])
    if sys.prefix == sys.base_prefix and not TEST:
        sys.exit("[!] Run this with the project's .venv (use make_portable_windows.bat).")

    def ignore(folder, names):
        out = {n for n in names if n == "__pycache__"}
        if pathlib.Path(folder) == site:
            for n in names:
                base = n.split("-")[0].lower()
                if base in SKIP_LIBS or n.endswith(".pth"):
                    out.add(n)
        return out

    shutil.copytree(site, dest, ignore=ignore)
    print(f"   libraries copied from {site}")


def copy_app(dest):
    def ignore(folder, names):
        out = {n for n in names if n in SKIP_APP or n.endswith(".pyc")}
        if pathlib.Path(folder) == ROOT:
            out |= {n for n in names if n.startswith("python-") and n.endswith(".zip")}
        return out

    shutil.copytree(ROOT, dest, ignore=ignore)
    if (dest / "instance").exists():
        print("   project copied, with instance/ (database, keys, search model)")
    else:
        print("   project copied, but instance/ was not found: run start_windows.bat once\n"
              "   first, so the copy has the database, the admin account and the model.")


def self_test(python_exe, app_dir):
    code = ("from badeel import create_app; import sklearn, cryptography; "
            "c = create_app().test_client(); r = c.get('/'); "
            "print('   home page:', r.status_code); assert r.status_code == 200")
    subprocess.run([str(python_exe), "-c", code], cwd=app_dir, check=True)


def main():
    if os.name != "nt" and not TEST:
        sys.exit("This script is for Windows.")
    if OUT.exists():
        step(f"Removing the old {OUT.name}")
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    if not TEST:
        step("1/4 Python (embeddable, from python.org)")
        get_python(OUT / "python")
    step("2/4 Libraries")
    copy_libs(OUT / "libs")
    step("3/4 Project")
    copy_app(OUT / "app")
    (OUT / "Start_Badeel.bat").write_bytes(START_BAT.encode("ascii"))
    (OUT / "Open_Terminal.bat").write_bytes(TERMINAL_BAT.encode("ascii"))
    if not TEST:
        step("4/4 Testing the copy")
        self_test(OUT / "python" / "python.exe", OUT / "app")
    print(f"\nDone: {OUT}\n"
          "Copy this whole folder to a USB stick. On the other computer copy it to the\n"
          "Desktop and double-click Start_Badeel.bat. Delete it from that computer afterwards.")


if __name__ == "__main__":
    main()
