"""测试发送 '移动到位置A' 的端到端响应时间"""
import asyncio
import json
import time
import sys

import aiohttp

WS_URL = "http://127.0.0.1:8765/ws/agent"
SESSION_ID = "test-timing-008"
MESSAGE = "移动到位置A"


async def main() -> int:
    start = time.perf_counter()
    t_first_token: float | None = None
    t_first_event: float | None = None
    event_count = 0
    final_text_parts: list[str] = []
    finished = False

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(WS_URL, heartbeat=20) as ws:
            # 发消息
            await ws.send_json({
                "type": "message",
                "session_id": SESSION_ID,
                "actor_id": "local-operator",
                "content": MESSAGE,
                "stream": True,
            })
            print(f"[0.000s] 已发送: {MESSAGE!r}")
            print("-" * 60)

            # 收事件，直到 turn 结束
            async for msg in ws:
                if msg.type is aiohttp.WSMsgType.TEXT:
                    elapsed = time.perf_counter() - start
                    try:
                        frame = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    event = frame.get("event")
                    if event == "ready":
                        continue

                    if t_first_event is None:
                        t_first_event = elapsed

                    # 累计文本流
                    # 注意：delta 是流式增量，final(message) 是完整回复
                    # 收到 final 时应替换而非追加，避免重复
                    # tool_hint (kind=tool_hint) 是工具进度提示，单独打印不累计
                    kind = frame.get("kind")
                    text_chunk = (
                        frame.get("text")
                        or (frame.get("data") or {}).get("text")
                        or (frame.get("delta") or {}).get("text")
                    )
                    if isinstance(text_chunk, str) and text_chunk:
                        if kind == "tool_hint":
                            # 工具进度提示，单独打印
                            print(f"[{elapsed:6.3f}s] 🔧 提示: {text_chunk}")
                            continue
                        if t_first_token is None:
                            t_first_token = elapsed
                            print(f"[{elapsed:6.3f}s] 首个文本 token")
                        if event == "message":
                            # final 事件 — 完整回复，替换累积内容
                            final_text_parts = [text_chunk]
                        else:
                            # delta 事件 — 流式增量
                            final_text_parts.append(text_chunk)
                        continue

                    # 打印关键事件
                    if event in ("turn_complete", "turn_end", "done", "finished"):
                        event_count += 1
                        print(f"[{elapsed:6.3f}s] 事件: {event}")
                        finished = True
                        break
                    elif event in ("tool_call", "tool_start", "tool_end", "tool_result"):
                        event_count += 1
                        tool_name = (
                            frame.get("tool")
                            or (frame.get("data") or {}).get("tool")
                            or (frame.get("name") or "")
                        )
                        print(f"[{elapsed:6.3f}s] 工具事件: {event} {tool_name}")
                    elif event == "error":
                        print(f"[{elapsed:6.3f}s] 错误: {frame.get('detail')}")
                        return 1
                    else:
                        event_count += 1
                        # 详细打印 message 事件中的 tool_events
                        if event == "message":
                            tool_events = frame.get("tool_events") or []
                            text_preview = (frame.get("text") or "")[:80]
                            print(f"[{elapsed:6.3f}s] message kind={frame.get('kind')} text={text_preview!r}")
                            for idx, te in enumerate(tool_events):
                                phase = te.get("phase") or te.get("event") or "?"
                                tname = te.get("name") or te.get("tool") or "?"
                                targs = te.get("arguments") or te.get("args") or {}
                                tresult = te.get("result") or {}
                                # 摘要
                                args_str = json.dumps(targs, ensure_ascii=False)[:200]
                                result_state = (
                                    tresult.get("state")
                                    if isinstance(tresult, dict) else None
                                )
                                print(f"           tool_event[{idx}] phase={phase} name={tname} state={result_state}")
                                if args_str:
                                    print(f"             args={args_str}")
                        else:
                            short = json.dumps(frame, ensure_ascii=False)[:120]
                            print(f"[{elapsed:6.3f}s] {short}")

                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    print(f"[{time.perf_counter() - start:6.3f}s] WebSocket 关闭: {msg.type}")
                    break

    total = time.perf_counter() - start
    print("-" * 60)
    print(f"总耗时:        {total:.3f}s")
    print(f"首事件:        {t_first_event:.3f}s" if t_first_event else "首事件:        -")
    print(f"首 token:      {t_first_token:.3f}s" if t_first_token else "首 token:      -")
    print(f"事件总数:      {event_count}")
    print(f"完成标志:      {'✅' if finished else '❌'}")
    full_text = "".join(final_text_parts)
    print(f"回复文本长度:  {len(full_text)} 字符")
    print(f"回复全文:\n{full_text}")
    return 0 if finished else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(130)
