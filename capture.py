"""오디오 캡처 모듈: 두 입력 장치(고객=USB 사운드카드, 나=내장마이크)를 동시에 열어
(화자, 24kHz mono int16 청크)를 큐로 내보낸다. STT 단계가 이 큐를 소비한다.
24kHz인 이유: OpenAI 스트리밍 전사 API의 pcm16 입력 규격이 24kHz.

테스트 모드는 장치 대신 wav 파일을 1배속으로 흘려서 실제 통화 없이 파이프라인을 검증한다.
녹음 파일 변환: afconvert -f WAVE -d LEI16@24000 -c 1 in.m4a out.wav

단독 실행:
    uv run capture.py --list                      # 장치 목록
    uv run capture.py --customer 2 --me 3         # 10초 캡처 → recordings/에 저장
    uv run capture.py --source test.wav           # 파일을 1배속으로 '고객' 채널에 흘리기
"""
import argparse
import queue
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

SR = 24000
CHUNK_MS = 100
CHUNK_SAMPLES = SR * CHUNK_MS // 1000


def find_device(name_part: str) -> int:
    """입력 장치를 번호가 아니라 이름 조각으로 찾는다 (USB 재연결 시 번호가 바뀌므로)."""
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0 and name_part.lower() in dev["name"].lower():
            return i
    raise RuntimeError(f"입력 장치를 못 찾음: {name_part}")


class Capture:
    """장치들을 열고 (speaker, int16 ndarray) 청크를 self.q에 넣는다."""

    def __init__(self, customer_device=None, me_device=None):
        self.q: queue.Queue = queue.Queue()
        self._streams = []
        for speaker, dev in (("customer", customer_device), ("me", me_device)):
            if dev is None:
                continue
            self._streams.append(sd.InputStream(
                device=dev, samplerate=SR, channels=1, dtype="int16",
                blocksize=CHUNK_SAMPLES, callback=self._callback(speaker)))

    def _callback(self, speaker):
        def cb(indata, frames, t, status):
            self.q.put((speaker, indata[:, 0].copy()))
        return cb

    def start(self):
        for s in self._streams:
            s.start()

    def stop(self):
        for s in self._streams:
            s.stop()
            s.close()


class FileCapture:
    """wav 파일(24kHz mono int16)을 1배속으로 '고객' 채널 청크로 내보낸다."""

    def __init__(self, path: str):
        self.q: queue.Queue = queue.Queue()
        self._path = path
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.done = False

    def _run(self):
        with wave.open(self._path, "rb") as w:
            assert w.getframerate() == SR and w.getnchannels() == 1, \
                f"{SR}Hz mono wav 필요 (afconvert로 변환하세요)"
            start = time.monotonic()
            i = 0
            while True:
                frames = w.readframes(CHUNK_SAMPLES)
                if not frames:
                    break
                # 1배속 유지: i번째 청크는 시작 후 i*CHUNK_MS ms 시점에 내보낸다
                target = start + i * CHUNK_MS / 1000
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                self.q.put(("customer", np.frombuffer(frames, dtype=np.int16)))
                i += 1
        self.done = True

    def start(self):
        self._thread.start()

    def stop(self):
        pass


def _level_bar(chunk: np.ndarray) -> str:
    peak = np.abs(chunk).max() / 32768
    return "#" * int(peak * 40)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--list", action="store_true")
    p.add_argument("--customer", type=int, help="고객(USB 사운드카드) 장치 번호")
    p.add_argument("--me", type=int, help="내 마이크 장치 번호")
    p.add_argument("--source", help="테스트용 wav 파일 경로")
    p.add_argument("--seconds", type=int, default=10)
    args = p.parse_args()

    if args.list:
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                print(f"[{i}] {dev['name']}")
        return

    if args.source:
        cap = FileCapture(args.source)
    else:
        cap = Capture(customer_device=args.customer, me_device=args.me)

    recorded = {"customer": [], "me": []}
    cap.start()
    print(f"{args.seconds}초간 캡처 중... (파일 모드는 파일 끝까지)")
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        try:
            speaker, chunk = cap.q.get(timeout=0.5)
        except queue.Empty:
            if isinstance(cap, FileCapture) and cap.done:
                break
            continue
        recorded[speaker].append(chunk)
        print(f"\r{speaker:8s} [{_level_bar(chunk):40s}]", end="")
    cap.stop()
    print()

    Path("recordings").mkdir(exist_ok=True)
    for speaker, chunks in recorded.items():
        if not chunks:
            continue
        path = f"recordings/test_{speaker}.wav"
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(np.concatenate(chunks).tobytes())
        print(f"저장: {path} ({len(chunks) * CHUNK_MS / 1000:.1f}초)")


if __name__ == "__main__":
    main()
