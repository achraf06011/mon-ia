"""Lanceur « application » : démarre le serveur en arrière-plan (sans fenêtre noire)
puis ouvre l'agent dans sa propre fenêtre, comme une vraie application."""
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).parent
PORT = 8002
URL = f"http://localhost:{PORT}"


def server_up() -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def start_server():
    python = Path(sys.executable).with_name("python.exe")  # pythonw -> python (+ pas de console)
    subprocess.Popen(
        [str(python), str(HERE / "web.py")],
        cwd=HERE,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    for _ in range(40):
        if server_up():
            return
        time.sleep(0.25)


def open_window():
    candidates = [
        os.environ.get("PROGRAMFILES", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("PROGRAMFILES(X86)", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("LOCALAPPDATA", "") + r"\Google\Chrome\Application\chrome.exe",
        os.environ.get("PROGRAMFILES(X86)", "") + r"\Microsoft\Edge\Application\msedge.exe",
        os.environ.get("PROGRAMFILES", "") + r"\Microsoft\Edge\Application\msedge.exe",
    ]
    for exe in candidates:
        if Path(exe).is_file():
            subprocess.Popen([exe, f"--app={URL}", "--window-size=1200,820"])
            return
    webbrowser.open(URL)


if __name__ == "__main__":
    if not server_up():
        start_server()
    open_window()
