# TESTING.md — 테스트 절차 (새 세션에서 바로 이어 쓰기용)

> 새 스레드를 열었다면: 이 문서 + [PLAN.md](PLAN.md)의 "🔴 최우선 검증 — STT" 섹션을 먼저 읽는다.

## 현재 상태 (2026-07-07)

- V1(오프라인 정확도), V2(1배속 지연) — ✅ 완료, 결과 양호 (아래 참고)
- V3(실제 통화 검증) — ⏳ 다음 할 일. 아래 절차대로 진행

## V1 — 오프라인 정확도 테스트

```bash
cd /Users/manager/Desktop/nophone
uv run stt_eval.py --source sample/test_call.wav                 # 전체(517초), 고속, 눈으로 정확도 검토
uv run stt_eval.py --source sample/test_call_60s.wav --realtime  # 60초, 1배속, 지연(ms) 측정
```

옵션: `--model gpt-4o-mini-transcribe`(모델 비교) · `--no-glossary`(용어집 효과 비교)

**기존 결과**: 숫자·회사명("위시켓", "3천만원", "11개 병원", "11월/12월") 정확히 인식. 도메인 용어("전원 연계 방송 플랫폼")는 `glossary.txt`에 추가 후 개선됨. 실시간 지연 평균 약 0.7~1초.

## V2 — 지연 측정
V1의 `--realtime` 옵션이 곧 V2. 출력 맨 아래 "발화 N건 · 지연 평균 Xms" 확인.

## V3 — 실제 통화 검증 (다음 할 일)

**사전 준비**: USB 사운드카드가 맥에 꽂혀 있어야 함 (전화기→젠더→Y분배기→USB사운드카드→맥).

**1단계 — 하드웨어 신호 확인**
```bash
uv run check_devices.py            # 장치 목록에서 USB Audio Device 번호 확인
uv run check_devices.py <번호>      # 통화 중 상대방이 말할 때 "신호 들어옴 ✅" 확인
```

**2단계 — 서버를 실전 모드로 (파일 아님, 실제 장치)**
```bash
uv run server.py
```

**3단계 — 브라우저**: `http://localhost:8000` (검증용 페이지 — 정식 디자인은 `static/mockup.html`이며 아직 미연결)

**4단계 — 통화**
- 휴대폰 → IP전화기로 전화 걸기 → 수화기 들기 → 웹에서 **[통화 시작]** 클릭
- 상대방(휴대폰) 말 → `고객` 자막 / 내(수화기) 말 → `나` 자막
- 확인할 것: ① 고객/나 채널 분리 정상 ② 실시간으로 자막이 따라오는지(지연 체감) ③ 숫자·용어 정확도 ④ 사이드톤(내 목소리가 고객 채널에 새는지)
- 종료: 웹 **[통화 종료]** 클릭 → 서버 터미널 `Ctrl+C`

**5단계 — 저장 확인**
```bash
sqlite3 data/nophone.db "SELECT speaker, ms, text FROM utterances ORDER BY ms;"
```

## V4 — 엔진 결정
V1~V3 결과 종합해 OpenAI(`gpt-4o-transcribe`) 확정 또는 Return Zero(RTZR) 등 대안 A/B. PLAN.md에 결과 기록.

## 알아두면 좋은 것
- **코드를 고치면 서버를 껐다 켜야** 반영됨 (Ctrl+C 후 재실행)
- 용어 추가는 `glossary.txt`에 한 줄씩 (git 제외 파일이라 직접 관리)
- USB 장치가 재연결 시 번호가 바뀔 수 있어 `server.py`는 이름으로 자동 탐색함 (`CUSTOMER_DEVICE_NAME="USB Audio"`)
