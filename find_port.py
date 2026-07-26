"""查找占用 8765 端口的进程"""
import subprocess

r = subprocess.run(
    ["netstat", "-ano"],
    capture_output=True,
    text=True,
    encoding="gbk",
    errors="ignore",
)
for line in r.stdout.splitlines():
    if "8765" in line and "LISTENING" in line:
        print(line.strip())
        parts = line.split()
        if parts:
            pid = parts[-1]
            print(f"PID={pid}")
            pr = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "LIST"],
                capture_output=True,
                text=True,
                encoding="gbk",
                errors="ignore",
            )
            print(pr.stdout)
