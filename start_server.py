"""启动 robot-server，显式设置 NANOBOT_HOME"""
import os
import subprocess
import sys

home = os.path.join(os.environ["APPDATA"], "motionflow-ai", "runtime")
env = os.environ.copy()
env["NANOBOT_HOME"] = home

cmd = [
    r"d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1\.venv\Scripts\python.exe",
    "-m",
    "robot_server.cli",
    "--host",
    "127.0.0.1",
    "--port",
    "8765",
]
print(f"NANOBOT_HOME={home}")
print(" ".join(cmd))
sys.stdout.flush()
subprocess.run(cmd, env=env, cwd=r"d:\learn\yjcao\nanobot-robotic-arms\nanobot-main-1")
