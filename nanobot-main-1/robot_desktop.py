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
    body { font-family: Arial, sans-serif; margin: 0; background: #f4f6f8; color: #17202a; }
    main { max-width: 1180px; margin: 0 auto; padding: 20px; }
    h1 { margin: 0 0 14px; font-size: 28px; }
    h2 { font-size: 16px; margin: 18px 0 8px; }
    textarea, input { width: 100%; box-sizing: border-box; border: 1px solid #c9d0da; padding: 8px; }
    textarea { min-height: 86px; }
    button { margin: 5px 5px 5px 0; padding: 8px 12px; border: 1px solid #aeb7c3; background: #fff; cursor: pointer; }
    button.danger { background: #b42318; border-color: #b42318; color: #fff; font-weight: 700; }
    audio { display: block; width: 100%; margin: 10px 0; }
    label { display: block; font-size: 12px; color: #5d6878; }
    label span { display: block; margin-bottom: 4px; }
    .layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; align-items: start; }
    .panel { background: #ffffff; border: 1px solid #d6dae1; padding: 14px; }
    .status-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 12px 0; }
    .status-item { background: #ffffff; border: 1px solid #d6dae1; padding: 10px; }
    .status-label { display: block; color: #5d6878; font-size: 12px; margin-bottom: 4px; }
    .status-value { font-weight: 700; }
    .status-message { background: #eef4ff; border: 1px solid #c8d9f3; padding: 10px; margin: 0 0 12px; }
    .grid-six { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; }
    .grid-four { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
    .confirm-row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }
    pre { background: #ffffff; border: 1px solid #d6dae1; padding: 12px; overflow: auto; min-height: 360px; }
    @media (max-width: 900px) { .layout, .status-strip, .grid-six, .grid-four, .confirm-row { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <h1>Robot AI</h1>
    <section id="operatorStatus" aria-label="operator status">
      <div class="status-strip">
        <div class="status-item"><span class="status-label">Backend</span><span id="backendMode" class="status-value">unknown</span></div>
        <div class="status-item"><span class="status-label">Control</span><span id="backendControl" class="status-value">unknown</span></div>
        <div class="status-item"><span class="status-label">Config</span><span id="backendConfig" class="status-value">unknown</span></div>
        <div class="status-item"><span class="status-label">Device</span><span id="deviceState" class="status-value">unknown</span></div>
      </div>
      <div id="backendMessage" class="status-message">Waiting for status...</div>
    </section>

    <div class="layout">
      <section class="panel">
        <h2>Conversation</h2>
        <textarea id="message" placeholder="输入机械手指令或对话"></textarea>
        <button onclick="sendMessage()">发送</button>
        <button onclick="refreshStatus()">查询状态</button>
        <button onclick="runReadonlyDiagnostics()">Read-only diagnostics</button>
        <button onclick="callApi('get_voice_state')">语音状态</button>
        <button onclick="synthesizeSpeech()">朗读</button>
        <audio id="audioPlayer" controls></audio>

        <h2>Restricted Operator Controls</h2>
        <button class="danger" onclick="systemControl('emergency_stop')">E-STOP</button>
        <button onclick="systemControl('pause')">Pause</button>
        <button onclick="systemControl('resume')">Resume</button>
        <button onclick="systemControl('release_emergency_stop')">Release E-STOP</button>
        <button onclick="systemControl('release_cancel')">Release Cancel</button>
        <button onclick="systemControl('stop_current')">Stop Current</button>

        <h2>Func108 Linear Interpolation</h2>
        <div class="grid-six">
          <label><span>X</span><input id="poseX" type="number" value="900" step="0.001"></label>
          <label><span>Y</span><input id="poseY" type="number" value="0" step="0.001"></label>
          <label><span>Z</span><input id="poseZ" type="number" value="999" step="0.001"></label>
          <label><span>RX</span><input id="poseRx" type="number" value="0" step="0.001"></label>
          <label><span>RY</span><input id="poseRy" type="number" value="0" step="0.001"></label>
          <label><span>RZ</span><input id="poseRz" type="number" value="0" step="0.001"></label>
        </div>
        <div class="grid-four">
          <label><span>Speed %</span><input id="speedPct" type="number" value="5" step="0.1"></label>
          <label><span>Accel %</span><input id="accelPct" type="number" value="5" step="0.1"></label>
          <label><span>Decel %</span><input id="decelPct" type="number" value="5" step="0.1"></label>
          <label><span>Allowed IO</span><input id="allowedIo" value="2,3,4"></label>
        </div>
        <div class="grid-four">
          <label><span>R min</span><input id="rMin" type="number" value="800" step="0.001"></label>
          <label><span>R max</span><input id="rMax" type="number" value="1000" step="0.001"></label>
          <label><span>Z min</span><input id="zMin" type="number" value="900" step="0.001"></label>
          <label><span>Z max</span><input id="zMax" type="number" value="1100" step="0.001"></label>
        </div>
        <textarea id="pathJson" placeholder='Optional continuous path JSON: [{"x":900,"y":0,"z":999,"rx":0,"ry":0,"rz":0}]'></textarea>
        <button onclick="linearMove()">Dry-run / execute line</button>
        <button onclick="linearPath()">Dry-run / execute path</button>

        <h2>Delay / IO</h2>
        <div class="grid-four">
          <label><span>Delay seconds</span><input id="delaySeconds" type="number" value="0.25" step="0.01"></label>
          <label><span>IO number</span><input id="ioNumber" type="number" value="3"></label>
          <label><span>IO state</span><input id="ioEnabled" type="checkbox" checked></label>
        </div>
        <button onclick="operatorDelay()">Delay</button>
        <button onclick="operatorIo()">IO write</button>
      </section>

      <aside class="panel">
        <h2>Real Execution Gate</h2>
        <div class="confirm-row">
          <label><input id="executeReal" type="checkbox"> Execute real</label>
          <label><input id="workAreaClear" type="checkbox"> Work area clear</label>
        </div>
        <label><input id="estopReady" type="checkbox"> Physical E-STOP is ready</label>
        <label><span>Confirmation code</span><input id="confirmationCode" placeholder="EXECUTE_ZMOTION_REAL"></label>
        <pre id="output">Ready</pre>
      </aside>
    </div>
  </main>
  <script>
    const output = document.getElementById("output");
    const audioPlayer = document.getElementById("audioPlayer");
    const backendMode = document.getElementById("backendMode");
    const backendControl = document.getElementById("backendControl");
    const backendConfig = document.getElementById("backendConfig");
    const deviceState = document.getElementById("deviceState");
    const backendMessage = document.getElementById("backendMessage");
    let lastReplyText = "";

    function show(value) { output.textContent = JSON.stringify(value, null, 2); }
    async function callApi(name) { show(await window.pywebview.api[name]()); }
    function numberValue(id) { return Number(document.getElementById(id).value); }
    function confirmationValues() {
      return [
        document.getElementById("executeReal").checked,
        document.getElementById("workAreaClear").checked,
        document.getElementById("estopReady").checked,
        document.getElementById("confirmationCode").value
      ];
    }
    function motionArgs() {
      return [
        numberValue("speedPct"), numberValue("accelPct"), numberValue("decelPct"),
        numberValue("rMin"), numberValue("rMax"), numberValue("zMin"), numberValue("zMax")
      ];
    }
    function poseFromInputs() {
      return {
        x: numberValue("poseX"), y: numberValue("poseY"), z: numberValue("poseZ"),
        rx: numberValue("poseRx"), ry: numberValue("poseRy"), rz: numberValue("poseRz")
      };
    }
    function allowedIo() {
      return document.getElementById("allowedIo").value
        .split(",")
        .map((value) => Number(value.trim()))
        .filter((value) => Number.isFinite(value));
    }
    function renderOperatorStatus(result) {
      const backend = result.data && result.data.backend ? result.data.backend : {};
      const robotState = result.data && result.data.robot_state ? result.data.robot_state : {};
      const missingConfig = backend.missing_config && backend.missing_config.length ? backend.missing_config.join(", ") : "missing";
      backendMode.textContent = backend.mode || "unknown";
      backendControl.textContent = backend.control_enabled ? "enabled" : "read-only";
      backendConfig.textContent = backend.configuration_ready ? "ready" : missingConfig;
      deviceState.textContent = robotState.connected_real_device ? "connected" : robotState.mode || "not connected";
      backendMessage.textContent = backend.message || result.message || "Status unavailable.";
    }
    async function refreshStatus() {
      const result = await window.pywebview.api.health();
      renderOperatorStatus(result);
      show(result);
    }
    async function runReadonlyDiagnostics() {
      const confirmed = window.confirm("Read-only diagnostics will only read controller status. Continue?");
      const result = await window.pywebview.api.run_zmotion_readonly_diagnostics(confirmed);
      renderOperatorStatus(result);
      show(result);
    }
    async function systemControl(action) {
      show(await window.pywebview.api.operator_system_control(action, ...confirmationValues()));
    }
    async function linearMove() {
      show(await window.pywebview.api.operator_linear_move(poseFromInputs(), ...motionArgs(), ...confirmationValues()));
    }
    async function linearPath() {
      const text = document.getElementById("pathJson").value.trim();
      const points = text ? JSON.parse(text) : [poseFromInputs()];
      show(await window.pywebview.api.operator_linear_path(points, ...motionArgs(), ...confirmationValues()));
    }
    async function operatorDelay() {
      show(await window.pywebview.api.operator_delay(numberValue("delaySeconds"), ...confirmationValues()));
    }
    async function operatorIo() {
      show(await window.pywebview.api.operator_io(numberValue("ioNumber"), document.getElementById("ioEnabled").checked, allowedIo(), ...confirmationValues()));
    }
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
    window.addEventListener("pywebviewready", refreshStatus);
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
