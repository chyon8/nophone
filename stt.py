"""실시간 STT: capture 큐의 오디오를 OpenAI 스트리밍 전사 API(웹소켓)로 보내
화자별 텍스트를 콜백으로 내보낸다. 화자마다 별도 세션을 열어 화자 구분을 유지한다.

단독 실행:
    uv run stt.py --source sample/test_call.wav   # 녹음 파일 1배속 전사 테스트
    uv run stt.py --customer 2 --me 3             # 라이브 전사
"""
import argparse
import asyncio
import base64
import json
import os
import threading
from pathlib import Path

import websockets
from dotenv import load_dotenv

from capture import Capture, FileCapture

# gpt-4o-transcribe: mini보다 정확 (고유명사 인식 확인됨, 예: "위시켓"). 협대역 전화음질엔 정확도 우선.
STT_MODEL = "gpt-4o-transcribe"
URL = "wss://api.openai.com/v1/realtime?intent=transcription"
LABELS = {"customer": "고객", "me": "나"}


def load_glossary_prompt() -> str:
    """glossary.txt의 용어들을 STT 프롬프트 문자열로 만든다. 없으면 빈 문자열."""
    path = Path(__file__).parent / "glossary.txt"
    if not path.exists():
        return ""
    terms = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith("#")]
    if not terms:
        return ""
    return "다음은 IT 프로젝트 상담 통화입니다. 자주 등장하는 고유명사·용어: " + ", ".join(terms)


def _is_prompt_echo(text: str, glossary: str) -> bool:
    """전사 결과가 용어집 프롬프트를 그대로 되뇐 환각인지 판정한다.
    희미하거나 애매한 소리가 들어오면 모델이 프롬프트 문자열(또는 그 일부)을 그대로 뱉는데,
    공백을 무시한 전사가 프롬프트 안에 통째로 들어있으면 에코로 본다."""
    if not glossary:
        return False
    squash = lambda s: "".join(s.split())
    return squash(text) in squash(glossary)


async def stt_session(speaker: str, audio_q: asyncio.Queue, on_event):
    """화자 1명분 전사 세션. audio_q에서 int16 청크를 받아 보내고 이벤트마다 on_event 호출.

    on_event(speaker, kind, text):
      kind='speech'    발화 시작 감지 (text=None)
      kind='stopped'   발화 종료 감지 (text=None) — 반응속도 측정의 기준점(t=0)
      kind='delta'     전사 스트리밍 조각
      kind='completed' 확정 문장
      kind='drop'      용어집 프롬프트 에코로 판정돼 버려진 발화 (text=None) — 진행 중 회색 줄 정리용
    """
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    transcription = {"model": STT_MODEL, "language": "ko"}
    glossary = load_glossary_prompt()
    if glossary:
        transcription["prompt"] = glossary
    async with websockets.connect(URL, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {"input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": transcription,
                    "turn_detection": {"type": "server_vad", "silence_duration_ms": 500},
                }},
            },
        }))

        async def sender():
            while True:
                chunk = await audio_q.get()
                if chunk is None:
                    break
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk.tobytes()).decode(),
                }))

        async def receiver():
            async for msg in ws:
                ev = json.loads(msg)
                t = ev.get("type", "")
                if t == "input_audio_buffer.speech_started":
                    on_event(speaker, "speech", None)
                elif t == "input_audio_buffer.speech_stopped":
                    on_event(speaker, "stopped", None)
                elif t == "conversation.item.input_audio_transcription.delta":
                    if ev.get("delta"):
                        on_event(speaker, "delta", ev["delta"])
                elif t == "conversation.item.input_audio_transcription.completed":
                    text = ev.get("transcript", "").strip()
                    if not text:
                        continue
                    if _is_prompt_echo(text, glossary):
                        on_event(speaker, "drop", None)   # 용어집 프롬프트 에코 → 버림
                    else:
                        on_event(speaker, "completed", text)
                elif t == "error":
                    print(f"\n[STT 오류/{speaker}] {ev.get('error')}")

        await asyncio.gather(sender(), receiver())


async def run(cap, speakers, on_event):
    """capture 큐를 화자별 asyncio 큐로 분배하고 세션들을 돌린다."""
    loop = asyncio.get_running_loop()
    queues = {s: asyncio.Queue() for s in speakers}

    def pump():
        while True:
            speaker, chunk = cap.q.get()
            asyncio.run_coroutine_threadsafe(queues[speaker].put(chunk), loop)

    threading.Thread(target=pump, daemon=True).start()
    cap.start()
    tasks = [asyncio.create_task(stt_session(s, queues[s], on_event)) for s in speakers]

    if isinstance(cap, FileCapture):
        while not cap.done:
            await asyncio.sleep(0.5)
        await asyncio.sleep(5)  # 마지막 문장 전사가 돌아올 여유
        for t in tasks:
            t.cancel()
    else:
        await asyncio.gather(*tasks)


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--source", help="테스트용 wav 파일 (24kHz mono)")
    p.add_argument("--customer", type=int, help="고객(USB 사운드카드) 장치 번호")
    p.add_argument("--me", type=int, help="내 마이크 장치 번호")
    args = p.parse_args()

    if args.source:
        cap = FileCapture(args.source)
        speakers = ["customer"]
    else:
        cap = Capture(customer_device=args.customer, me_device=args.me)
        speakers = [s for s, d in (("customer", args.customer), ("me", args.me)) if d is not None]

    def on_event(speaker, kind, text):
        if kind == "completed":
            print(f"[{LABELS[speaker]}] {text}")

    try:
        asyncio.run(run(cap, speakers, on_event))
    except KeyboardInterrupt:
        pass
    finally:
        cap.stop()


if __name__ == "__main__":
    main()
