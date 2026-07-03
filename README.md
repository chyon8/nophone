# nophone — AI 통화 코파일럿

유선 IP전화 통화를 실시간으로 보조하는 시스템. 통화 음성을 실시간 STT로 받아 적고, AI가 다음 멘트를 제안하며, 버튼 하나로 견적 초안·요구사항 정리 등을 즉시 생성한다.

## 개발 로드맵

- **1차 (진행 중)**: 실시간 STT 자막 + AI 다음 멘트 제안 + 프롬프트 버튼 (견적 초안 / 요구사항 정리 / 절차 설명 / 통화 요약)
- **1.5차**: RAG — 과거 견적서·단가·절차 문서 기반 제안
- **2차**: 목소리 클로닝 TTS로 AI가 직접 통화 (ElevenLabs)

**도메인**: IT 프로젝트 수주 상담 (요구사항 파악, 견적, 개발 절차 안내)

## 하드웨어 구성

```
[IP전화기 헤드셋 포트]
    └─ 4극→3극 분리 젠더
         ├─ 마이크 구멍 ← 헤드셋 마이크 선 (내 목소리 → 상대방)
         └─ 스피커 구멍 → Y분배기
              ├─ 헤드셋 스피커 선 (내가 듣기)
              └─ AUX → USB 사운드카드 → Mac (상대방 목소리 캡처)

[맥북 내장 마이크] → 내 목소리 캡처 (화자 구분용)
```

두 입력이 장치 단위로 분리되어 있어 화자(고객/나) 구분이 자동으로 된다.

## 스택

Python 3.12 + uv · sounddevice (오디오 캡처) · OpenAI `gpt-4o-mini-transcribe` (스트리밍 STT) · OpenAI GPT-5 계열 (AI 제안) · FastAPI + WebSocket · 단일 HTML + 바닐라 JS · SQLite

## 문서

- [DESIGN.md](DESIGN.md) — 확정 설계 (스키마·UI/UX·정책)
- [PLAN.md](PLAN.md) — 개발 계획·청크·진행 상태
- [STYLE.md](STYLE.md) — 디자인 시스템 (UI 필수 준수)
- [CLAUDE.md](CLAUDE.md) — 작업 규칙

## 셋업

```bash
brew install uv
uv sync
cp .env.example .env   # OpenAI API 키 입력
```

## 사용법

```bash
# 오디오 장치 확인
uv run check_devices.py           # 장치 목록
uv run check_devices.py 3         # 3번 장치 입력 레벨 테스트

# 캡처 테스트
uv run capture.py --list                 # 입력 장치 목록
uv run capture.py --customer 2 --me 3    # 두 장치 동시 캡처 → recordings/ 저장
uv run capture.py --source test.wav      # 녹음 파일을 1배속으로 흘리는 테스트 모드
```

QuickTime 녹음(.m4a)을 테스트용으로 쓰려면 변환:

```bash
afconvert -f WAVE -d LEI16@24000 -c 1 녹음.m4a test.wav
```

## 개발 원칙

[CLAUDE.md](CLAUDE.md) 참고. 핵심:

- STT 모듈은 교체 가능하게 분리 (전화 협대역 음질 대비)
- 개발 테스트는 실제 통화 대신 녹음 파일 1배속 재생으로
- AI 제안은 발화 종료 시점에만 생성
- API 키는 `.env`, 커밋 금지
