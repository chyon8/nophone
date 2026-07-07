"""STT 검증 도구 (V1·V2): wav 파일을 전사해 타임스탬프 자막 + 발화종료→확정 지연(ms)을 낸다.

- 정확도(V1): 빠르게 흘려 전체 전사를 뽑아 눈으로 검토 (숫자·고유명사·프로젝트ID)
- 지연(V2): --realtime 으로 1배속 전송해 발화종료→텍스트 지연 측정

    uv run stt_eval.py --source sample/test_call.wav                 # full+용어집, 빠르게
    uv run stt_eval.py --source sample/test_call_60s.wav --realtime  # 1배속 지연 측정
    uv run stt_eval.py --source sample/test_call_60s.wav --model gpt-4o-mini-transcribe
    uv run stt_eval.py --source sample/test_call_60s.wav --no-glossary
"""
import argparse
import asyncio
import base64
import json
import os
import time
import wave

import websockets
from dotenv import load_dotenv

from stt import URL, load_glossary_prompt

CHUNK_MS = 100


async def evaluate(path, model, use_glossary, realtime):
    with wave.open(path, "rb") as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1, "24kHz mono wav 필요"
        audio = w.readframes(w.getnframes())
    dur = len(audio) / 2 / 24000
    print(f"파일 {path} · {dur:.1f}초 · 모델 {model} · 용어집 {'ON' if use_glossary else 'OFF'} "
          f"· {'1배속' if realtime else '고속'}\n" + "─" * 60)

    transcription = {"model": model, "language": "ko"}
    if use_glossary:
        g = load_glossary_prompt()
        if g:
            transcription["prompt"] = g

    headers = {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}
    latencies = []
    async with websockets.connect(URL, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {"type": "transcription", "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "transcription": transcription,
                "turn_detection": {"type": "server_vad", "silence_duration_ms": 500},
            }}},
        }))

        stopped_at = {}  # 발화종료 시각 (지연 측정용)

        async def sender():
            step = 24000 * CHUNK_MS // 1000 * 2  # bytes per chunk
            for i in range(0, len(audio), step):
                await ws.send(json.dumps({"type": "input_audio_buffer.append",
                                          "audio": base64.b64encode(audio[i:i + step]).decode()}))
                await asyncio.sleep(CHUNK_MS / 1000 if realtime else 0.008)
            await asyncio.sleep(6)  # 마지막 전사 여유

        async def receiver():
            async for msg in ws:
                ev = json.loads(msg)
                t = ev.get("type", "")
                if t == "input_audio_buffer.speech_stopped":
                    stopped_at["t"] = time.monotonic()
                elif t == "conversation.item.input_audio_transcription.completed":
                    text = ev.get("transcript", "").strip()
                    if not text:
                        continue
                    lat = None
                    if "t" in stopped_at:
                        lat = (time.monotonic() - stopped_at.pop("t")) * 1000
                        latencies.append(lat)
                    tag = f"  ({lat:.0f}ms)" if lat is not None else ""
                    print(f"{text}{tag}")
                elif t == "error":
                    print(f"[오류] {ev.get('error')}")

        send_task = asyncio.create_task(sender())
        try:
            await asyncio.wait_for(receiver(), timeout=dur + 20 if realtime else 90)
        except asyncio.TimeoutError:
            pass
        send_task.cancel()

    print("─" * 60)
    if latencies:
        latencies.sort()
        print(f"발화 {len(latencies)}건 · 지연 평균 {sum(latencies)/len(latencies):.0f}ms "
              f"· 중앙 {latencies[len(latencies)//2]:.0f}ms · 최대 {latencies[-1]:.0f}ms")


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--model", default="gpt-4o-transcribe")
    p.add_argument("--no-glossary", action="store_true")
    p.add_argument("--realtime", action="store_true")
    args = p.parse_args()
    asyncio.run(evaluate(args.source, args.model, not args.no_glossary, args.realtime))


if __name__ == "__main__":
    main()
