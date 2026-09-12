"""WebSocket frames for the robot server's public runtime event contract."""

from __future__ import annotations

from typing import Any

from ai_runtime.contracts import RuntimeEvent


def webui_frame_for_runtime_event(event: RuntimeEvent) -> dict[str, Any] | None:
    if event.kind == "delta":
        frame = _runtime_frame(event, "delta", text=event.payload.get("content", ""))
        if event.payload.get("stream_id"):
            frame["stream_id"] = event.payload["stream_id"]
        return frame
    if event.kind == "stream_end":
        frame = _runtime_frame(event, "stream_end")
        if event.payload.get("stream_id"):
            frame["stream_id"] = event.payload["stream_id"]
        return frame
    if event.kind == "tool_progress":
        frame = _runtime_frame(event, "message", text=event.payload.get("content", ""))
        frame["kind"] = "tool_hint" if event.payload.get("tool_hint") else "progress"
        if event.payload.get("tool_events"):
            frame["tool_events"] = event.payload["tool_events"]
        return frame
    if event.kind == "final":
        return _runtime_frame(event, "message", text=event.payload.get("content", ""))
    if event.kind == "turn_end":
        frame = _runtime_frame(event, "turn_end")
        frame.update({key: value for key, value in event.payload.items() if value is not None})
        return frame
    return None


def _runtime_frame(event: RuntimeEvent, frame_event: str, **payload: Any) -> dict[str, Any]:
    frame: dict[str, Any] = {"event": frame_event, "session_id": event.conversation_id}
    frame.update(payload)
    if event.request_id:
        frame["request_id"] = event.request_id
    return frame
