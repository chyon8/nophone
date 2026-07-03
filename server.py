"""서버 + 통화 세션 (청크 B): 캡처 → STT → DB 저장 + WebSocket 방송을 하나로 엮는다.

실행:
    uv run server.py                                  # 실전: 장치 이름으로 자동 탐색
    uv run server.py --source sample/test_call.wav    # 테스트: 녹취 파일 1배속
브라우저: http://localhost:8000
"""
import argparse
import asyncio
import json
import threading
import time
from datetime import datetime

import sounddevice as sd
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import db
from capture import Capture, FileCapture
from stt import stt_session

# 장치는 번호가 아니라 이름으로 찾는다 (USB 재연결 시 번호가 바뀌므로 — 검증에서 결정)
CUSTOMER_DEVICE_NAME = "USB Audio"
ME_DEVICE_NAME = "MacBook"
AGENT = "나"

app = FastAPI()
clients: set = set()
session = None
SOURCE = None  # --source 파일 경로 (없으면 실전 장치 모드)


def find_device(name_part: str) -> int:
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name_part.lower() in dev["name"].lower():
            return i
    raise RuntimeError(f"입력 장치를 못 찾음: {name_part}")


async def broadcast(msg: dict):
    dead = []
    for ws in clients:
        try:
            await ws.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


class CallSession:
    """통화 한 건: 시작 → 발화 저장·방송 → 종료."""

    def __init__(self, source=None):
        self.conn = db.connect()
        self.source = source
        self.call_id = None
        self.tasks = []
        self.cap = None
        self._speech_ms = {}   # 화자별 발화 시작 시점 (utterance.ms용)
        self._start = None

    async def start(self):
        self.call_id = db.create_call(self.conn, agent=AGENT)
        self._start = time.monotonic()
        if self.source:
            self.cap = FileCapture(self.source)
            speakers = ["customer"]
        else:
            self.cap = Capture(customer_device=find_device(CUSTOMER_DEVICE_NAME),
                               me_device=find_device(ME_DEVICE_NAME))
            speakers = ["customer", "me"]

        loop = asyncio.get_running_loop()
        queues = {s: asyncio.Queue() for s in speakers}

        def pump():
            while True:
                speaker, chunk = self.cap.q.get()
                asyncio.run_coroutine_threadsafe(queues[speaker].put(chunk), loop)

        threading.Thread(target=pump, daemon=True).start()
        self.cap.start()
        self.tasks = [asyncio.create_task(stt_session(s, queues[s], self.on_event)) for s in speakers]
        if isinstance(self.cap, FileCapture):
            self.tasks.append(asyncio.create_task(self._watch_file_end()))
        await broadcast({"type": "status", "state": "started", "call_id": self.call_id})

    async def _watch_file_end(self):
        while not self.cap.done:
            await asyncio.sleep(0.5)
        await asyncio.sleep(5)  # 마지막 문장 전사 여유
        await end_session()

    def on_event(self, speaker, kind, text):
        ms = int((time.monotonic() - self._start) * 1000)
        if kind == "speech":
            self._speech_ms[speaker] = ms
            asyncio.create_task(broadcast({"type": "speech", "speaker": speaker}))
        elif kind == "delta":
            asyncio.create_task(broadcast({"type": "partial", "speaker": speaker, "text": text}))
        elif kind == "completed":
            u_ms = self._speech_ms.pop(speaker, ms)
            db.add_utterance(self.conn, self.call_id, speaker, text, u_ms)
            asyncio.create_task(broadcast(
                {"type": "utterance", "speaker": speaker, "text": text, "ms": u_ms}))

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        self.cap.stop()
        db.update_call(self.conn, self.call_id,
                       ended_at=datetime.now().isoformat(timespec="seconds"))
        await broadcast({"type": "status", "state": "ended", "call_id": self.call_id})


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.post("/api/call/start")
async def start_call():
    global session
    if session:
        return {"error": "이미 통화 중"}
    session = CallSession(source=SOURCE)
    await session.start()
    return {"call_id": session.call_id}


@app.post("/api/call/end")
async def end_call():
    return await end_session()


async def end_session():
    global session
    if not session:
        return {"error": "통화 중 아님"}
    s, session = session, None
    await s.stop()
    return {"call_id": s.call_id}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clients.discard(ws)


if __name__ == "__main__":
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--source", help="테스트용 wav 파일 (24kHz mono) — 없으면 실전 장치 모드")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    SOURCE = args.source
    uvicorn.run(app, host="127.0.0.1", port=args.port)
