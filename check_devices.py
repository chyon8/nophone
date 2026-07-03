"""오디오 입력 장치 확인: 장치 목록 출력 후, 선택한 장치에서 3초간 입력 레벨을 측정한다.

사용법:
    uv run check_devices.py           # 장치 목록만 출력
    uv run check_devices.py <번호>    # 해당 장치에서 3초간 레벨 측정
"""
import sys

import numpy as np
import sounddevice as sd


def list_devices():
    print("=== 입력 가능한 오디오 장치 ===")
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            default = " (기본 입력)" if i == sd.default.device[0] else ""
            print(f"[{i}] {dev['name']}  채널:{dev['max_input_channels']}  "
                  f"샘플레이트:{int(dev['default_samplerate'])}{default}")


def level_test(device_index: int, seconds: int = 3):
    dev = sd.query_devices(device_index)
    sr = int(dev["default_samplerate"])
    print(f"'{dev['name']}'에서 {seconds}초간 녹음... 소리를 내보세요.")
    audio = sd.rec(int(seconds * sr), samplerate=sr, channels=1, device=device_index)
    sd.wait()
    peak = float(np.abs(audio).max())
    rms = float(np.sqrt((audio ** 2).mean()))
    bar = "#" * int(peak * 50)
    print(f"피크: {peak:.4f}  RMS: {rms:.4f}  [{bar}]")
    if peak < 0.001:
        print("→ 신호 없음. 연결/권한(시스템 설정 > 개인정보 보호 > 마이크)을 확인하세요.")
    else:
        print("→ 신호 들어옴 ✅")


if __name__ == "__main__":
    list_devices()
    if len(sys.argv) > 1:
        print()
        level_test(int(sys.argv[1]))
