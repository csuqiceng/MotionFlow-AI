from __future__ import annotations

from threading import Timer
from typing import Callable

from robot_ai.bridge import RobotApi
from robot_ai.runtime import (
    desktop_runtime_dependency_status,
    format_desktop_dependency_help,
)


HTML = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Robot AI</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #f6f7f9; color: #17202a; }
    main { max-width: 860px; margin: 0 auto; }
    textarea { width: 100%; min-height: 86px; box-sizing: border-box; }
    button { margin: 6px 6px 6px 0; padding: 8px 12px; }
    audio { display: block; width: 100%; margin: 10px 0; }
    pre { background: #ffffff; border: 1px solid #d6dae1; padding: 12px; overflow: auto; }
  </style>
</head>
<body>
  <main>
    <h1>Robot AI</h1>
    <textarea id="message" placeholder="输入机械手指令或对话"></textarea>
    <div>
      <button onclick="sendMessage()">发送</button>
      <button onclick="callApi('get_robot_state')">查询状态</button>
      <button onclick="moveX()">X +10</button>
      <button onclick="callApi('home')">回零</button>
      <button onclick="callApi('stop')">停止</button>
      <button onclick="callApi('get_voice_state')">语音状态</button>
      <button onclick="synthesizeSpeech()">朗读</button>
    </div>
    <audio id="audioPlayer" controls></audio>
    <pre id="output">Ready</pre>
  </main>
  <script>
    const output = document.getElementById("output");
    const audioPlayer = document.getElementById("audioPlayer");
    let lastReplyText = "";
    function show(value) { output.textContent = JSON.stringify(value, null, 2); }
    async function callApi(name) { show(await window.pywebview.api[name]()); }
    async function moveX() { show(await window.pywebview.api.move_axis("x", 10)); }
    async function sendMessage() {
      const text = document.getElementById("message").value;
      const result = await window.pywebview.api.send_message(text);
      if (result.ok && result.data && result.data.text) lastReplyText = result.data.text;
      show(result);
    }
    async function synthesizeSpeech() {
      const typedText = document.getElementById("message").value;
      const text = lastReplyText || typedText;
      const result = await window.pywebview.api.synthesize_speech(text);
      if (result.ok && result.data && result.data.audio_base64) {
        audioPlayer.src = `data:${result.data.mime_type};base64,${result.data.audio_base64}`;
        audioPlayer.play().catch(() => {});
      }
      show(result);
    }
  </script>
</body>
</html>
"""


def create_api() -> RobotApi:
    return RobotApi()


def launch_desktop_window(
    *,
    webview_module,
    start: bool = True,
    auto_close: bool = False,
    auto_close_delay_sec: float = 1.0,
    timer_factory: Callable[[float, Callable[[], None]], Timer] = Timer,
):
    window = webview_module.create_window(
        "Robot AI",
        html=HTML,
        js_api=create_api(),
        width=980,
        height=720,
    )
    if start:
        def close_later() -> None:
            timer_factory(auto_close_delay_sec, window.destroy).start()

        callback = None
        ready_event = getattr(getattr(window, "events", None), "_pywebviewready", None)
        if auto_close and ready_event is not None:
            ready_event += close_later
        elif auto_close:
            callback = close_later
        webview_module.start(callback)
    return window


def main() -> None:
    status = desktop_runtime_dependency_status()
    if not status["ready"]:
        raise RuntimeError(format_desktop_dependency_help(status))

    import webview

    launch_desktop_window(webview_module=webview)


if __name__ == "__main__":
    main()
