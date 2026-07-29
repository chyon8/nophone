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

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import cost
import customer_sim
import db
from capture import Capture, FileCapture, find_device
from stt import stt_session
from suggest import SYSTEM, Suggester

# 장치는 번호가 아니라 이름으로 찾는다 (USB 재연결 시 번호가 바뀌므로 — 검증에서 결정)
CUSTOMER_DEVICE_NAME = "USB Audio"
ME_DEVICE_NAME = "MacBook"
CUSTOMER_MODEL = "gpt-4.1"   # 매니저 모드에서 AI 고객 역
AGENT = "나"

app = FastAPI()
clients: set = set()
session = None
SOURCE = None  # --source 파일 경로 (없으면 실전 장치 모드)
DEBOUNCE_MS = 1200  # 고객 발화 조각 병합 대기(ms) — VAD 토막 방지 (--debounce-ms로 튜닝)


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

    def __init__(self, source=None, role="고객", briefing="", scenario=""):
        self.conn = db.connect()
        self.source = source
        self.role = role          # "고객"=내 마이크를 고객 채널로 / "매니저"=나 채널로
        self.briefing = briefing
        self.scenario = scenario  # 매니저 모드에서 AI 고객이 연기할 시나리오(진실+페르소나)
        self.call_id = None
        self.tasks = []
        self.cap = None
        self._speech_ms = {}   # 화자별 발화 시작 시점 (utterance.ms용)
        self._start = None
        # 제안 엔진(키워드 큐) — emit 이벤트를 그대로 WS로 방송한다. context_n=0 → 통화 전체
        self.suggester = Suggester(model="gpt-4.1", effort="off", context_n=0,
                                   briefing=briefing, emit=self._emit,
                                   debounce_ms=DEBOUNCE_MS)

    def _emit(self, kind, d):
        """Suggester 이벤트 → WS 방송. transcript는 on_event의 utterance가 이미 방송하므로 무시."""
        if kind == "usage":                       # 비용 기록 — 방송 없이 DB에만 (UI는 나중)
            db.add_usage_event(self.conn, self.call_id, **d)
            return
        if kind == "suggest_start":
            msg = {"type": "suggest_start"}
        elif kind == "suggest_delta":
            msg = {"type": "suggest_delta", "text": d["text"]}
        elif kind == "suggest_done":
            msg = {"type": "suggest_done", "text": d["text"],
                   "first_ms": round(d["first_ms"]), "total_ms": round(d["total_ms"])}
            if d["text"]:   # 제안 로그 저장 — 어떤 큐를 냈는지 기록(튜닝 분석 근거)
                db.add_suggestion(self.conn, self.call_id, db.BUILTIN_REPLY_ID,
                                  SYSTEM, d["text"], model=self.suggester.model)
        elif kind == "agenda":
            msg = {"type": "agenda", "items": d["items"]}
        else:
            return
        asyncio.create_task(broadcast(msg))

    async def start(self):
        self.call_id = db.create_call(self.conn, agent=AGENT)
        self._start = time.monotonic()
        if self.source:
            self.cap = FileCapture(self.source)
            speakers = ["customer"]
        elif self.role == "매니저":     # 내가 매니저 → 내 마이크를 '나' 채널로 (AI 고객은 청크 3)
            self.cap = Capture(me_device=find_device(ME_DEVICE_NAME))
            speakers = ["me"]
        else:                          # 내가 고객 → 내 마이크를 '고객' 채널로 (코파일럿이 매니저 질문 생성)
            self.cap = Capture(customer_device=find_device(ME_DEVICE_NAME))
            speakers = ["customer"]

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
        if self.briefing:                      # 사전 브리핑 → 어젠다(미리 준비한 질문) 표시
            asyncio.create_task(self.suggester.agenda())

    async def dismiss_briefing(self):
        """매니저가 '브리핑 무시'를 누름 → 이후 제안·공고에서 브리핑을 뺀다 (대화록만 기준)."""
        self.briefing = ""
        self.suggester.briefing = ""
        await broadcast({"type": "briefing_dismissed"})

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
        elif kind == "drop":
            self._speech_ms.pop(speaker, None)
            asyncio.create_task(broadcast({"type": "drop", "speaker": speaker}))
        elif kind == "completed":
            u_ms = self._speech_ms.pop(speaker, ms)
            db.add_utterance(self.conn, self.call_id, speaker, text, u_ms)
            asyncio.create_task(broadcast(
                {"type": "utterance", "speaker": speaker, "text": text, "ms": u_ms}))
        self.suggester.on_event(speaker, kind, text)   # 제안·채점 엔진에도 전달(발화종료 시 큐 생성)
        # 매니저 모드: 내 발화가 끝나면 AI 고객이 시나리오대로 반응 → 고객 턴으로 재주입
        if kind == "completed" and speaker == "me" and self.role == "매니저" and self.scenario:
            asyncio.create_task(self._inject_customer())

    async def _inject_customer(self):
        persona = {"me": "매니저", "customer": "나"}   # 고객 관점 라벨
        lines = [f"{persona[sp]}: {t}" for sp, t in self.suggester.transcript]
        t0 = time.monotonic()
        reply, resp = await customer_sim.respond(self.suggester.client, CUSTOMER_MODEL, self.scenario, lines)
        if resp is not None:      # AI 고객은 테스트 전용 비용 → kind로 구분해 기록
            db.add_usage_event(self.conn, self.call_id,
                               **cost.event("customer_sim", CUSTOMER_MODEL, resp, (time.monotonic() - t0) * 1000))
        self.on_event("customer", "stopped", None)
        self.on_event("customer", "completed", reply)

    async def stop(self):
        self.cap.stop()
        db.update_call(self.conn, self.call_id,
                       ended_at=datetime.now().isoformat(timespec="seconds"))
        # 공고 draft 생성 (F1) — task 취소보다 먼저. 파일 모드에선 stop()이 _watch_file_end
        # (=self.tasks 중 하나)에서 불리므로, self.tasks를 먼저 취소하면 다음 await에서
        # 자기 자신이 CancelledError로 끊겨 draft가 스킵된다.
        draft = None
        if self.suggester.transcript:
            try:
                draft = await self.suggester.make_draft()
            except Exception as e:
                print(f"[공고 draft 생성 실패] {e}")
        await broadcast({"type": "status", "state": "ended", "call_id": self.call_id})
        if draft:
            db.update_call(self.conn, self.call_id, summary=draft)
            await broadcast({"type": "draft", "text": draft})
            print(f"\n{'═' * 60}\n📋 공고 draft — call {self.call_id[:8]}\n{'═' * 60}\n{draft}\n")
        for t in self.tasks:
            t.cancel()


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.post("/api/call/start")
async def start_call(request: Request):
    global session
    if session:
        return {"error": "이미 통화 중"}
    try:
        data = await request.json()
    except Exception:
        data = {}
    session = CallSession(source=SOURCE, role=data.get("role", "고객"),
                          briefing=data.get("briefing", ""), scenario=data.get("scenario", ""))
    await session.start()
    return {"call_id": session.call_id}


@app.post("/api/call/dismiss-briefing")
async def dismiss_briefing():
    if not session:
        return {"error": "통화 중 아님"}
    await session.dismiss_briefing()
    return {"ok": True}


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
    p.add_argument("--debounce-ms", type=int, default=1200,
                   help="고객 발화 조각 병합 대기(ms) — VAD 토막 방지. 라이브 롤플레이에서 튜닝")
    args = p.parse_args()
    SOURCE = args.source
    DEBOUNCE_MS = args.debounce_ms
    uvicorn.run(app, host="127.0.0.1", port=args.port)
