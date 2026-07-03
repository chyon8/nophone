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

import websockets
from dotenv import load_dotenv

from capture import Capture, FileCapture

STT_MODEL = "gpt-4o-mini-transcribe"
URL = "wss://api.openai.com/v1/realtime?intent=transcription"
LABELS = {"customer": "고객", "me": "나"}


async def stt_session(speaker: str, audio_q: asyncio.Queue, on_text):
    """화자 1명분 전사 세션. audio_q에서 int16 청크를 받아 보내고, 확정 문장마다 on_text 호출."""
    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    async with websockets.connect(URL, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {"input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": {"model": STT_MODEL, "language": "ko"},
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
                if t == "conversation.item.input_audio_transcription.completed":
                    text = ev.get("transcript", "").strip()
                    if text:
                        on_text(speaker, text)
                elif t == "error":
                    print(f"\n[STT 오류/{speaker}] {ev.get('error')}")

        await asyncio.gather(sender(), receiver())


async def run(cap, speakers, on_text):
    """capture 큐를 화자별 asyncio 큐로 분배하고 세션들을 돌린다."""
    loop = asyncio.get_running_loop()
    queues = {s: asyncio.Queue() for s in speakers}

    def pump():
        while True:
            speaker, chunk = cap.q.get()
            asyncio.run_coroutine_threadsafe(queues[speaker].put(chunk), loop)

    threading.Thread(target=pump, daemon=True).start()
    cap.start()
    tasks = [asyncio.create_task(stt_session(s, queues[s], on_text)) for s in speakers]

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

    def on_text(speaker, text):
        print(f"[{LABELS[speaker]}] {text}")

    try:
        asyncio.run(run(cap, speakers, on_text))
    except KeyboardInterrupt:
        pass
    finally:
        cap.stop()


if __name__ == "__main__":
    main()
