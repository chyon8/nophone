"""제안 루프 (청크 D 프로토타입): 고객 발화가 끝나면 "다음에 그대로 읽을 질문"을 만들어
터미널에 띄우고, 발화종료 기준 반응속도(ms)를 측정한다. 화면(UI) 없음.

DESIGN.md 성공 기준:
  1순위 품질 — 수정 없이 소리내어 읽어도 자연스럽고 물어볼 가치가 있는가
  2순위 속도 — 발화종료 → 제안 첫 글자가 체감 2~3초 이내인가 (넘어야 할 바닥선)

    uv run suggest.py --source sample/test_call.wav          # 녹취 1배속으로 검증
    uv run suggest.py --source sample/test_call_60s.wav --model gpt-4.1-mini
    uv run suggest.py --briefing-file briefing.txt           # 실전 (장치 자동 탐색)
"""
import argparse
import asyncio
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

import stt
from capture import Capture, FileCapture
from server import find_device  # 장치는 번호가 아니라 이름으로 찾는다 (USB 재연결 대비)

# ── 도메인 프롬프트 v1 ─────────────────────────────────────────────────────────
# 이 시스템의 해자는 여기다 (DESIGN.md "왜 범용 도구로는 안 되는가").
# 체크리스트는 실제 위시켓 공고 등록 기준에 맞춰 사용자가 계속 다듬는다.
SYSTEM = """당신은 위시켓 매니저의 통화 코파일럿입니다.

상황: 매니저가 프로젝트 의뢰인과 전화 상담 중입니다. 목적은 이 프로젝트를 검수하고,
위시켓에 개발자 모집 공고로 등록할 수 있을 만큼 정보를 확보하는 것입니다.

임무: 방금 의뢰인의 말이 끝났습니다. 매니저가 **그대로 소리내어 읽을** 다음 대사를 하나만 쓰세요.

규칙:
- 조언이 아니라 대사를 쓴다. ("~라고 물어보세요" 금지 — 바로 읽을 문장만.)
- 1~2문장. 전화로 말하기 자연스러운 구어체 존댓말.
- 이미 답이 나온 것은 다시 묻지 않는다.
- 의뢰인이 방금 한 말을 짧게 받아 확인한 뒤 이어서 묻는 것이 자연스러우면 그렇게 한다.
- 의뢰인이 질문을 했다면, 그 질문에 답하는 대사를 먼저 쓴다.
- 그 외에는 아래 체크리스트 중 **아직 안 나왔고 공고 등록에 가장 중요한 것**을 묻는다.
- 대사만 출력한다. 따옴표·머리말·설명·이유 금지.

공고 등록에 필요한 정보 체크리스트:
1. 프로젝트 목적 · 해결하려는 문제
2. 결과물 형태 (웹 / 모바일앱(iOS·Android) / 데스크톱 / 기존 솔루션 연동)
3. 핵심 기능 범위 (1차에 반드시 넣을 것과 나중으로 미룰 것의 구분)
4. 기획·디자인 산출물 보유 여부 (기획서 · 화면설계 · 디자인 시안)
5. 예산 규모와 그 산정 근거
6. 희망 기간 · 마감 시점 (못 미루는 일정이 있는지)
7. 기술 스택 · 인프라 제약 (기존 시스템 연동, 서버 환경)
8. 검수 기준 · 산출물 (소스코드 인계, 테스트 범위)
9. 유지보수 · 운영 계획
10. 의사결정 구조 (실무 담당자, 최종 결정권자)
11. 참고 서비스 · 레퍼런스
"""
# ──────────────────────────────────────────────────────────────────────────────

LABELS = {"customer": "고객", "me": "나"}


def build_messages(transcript, briefing, context_n):
    system = SYSTEM
    glossary = stt.load_glossary_prompt()
    if glossary:
        system += f"\n{glossary}\n"
    if briefing:
        system += f"\n[사전 브리핑 — 통화 전에 파악된 프로젝트 정보]\n{briefing}\n"

    recent = transcript[-context_n:]
    lines = "\n".join(f"{LABELS[s]}: {t}" for s, t in recent)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"[대화록]\n{lines}\n\n방금 고객의 말이 끝났습니다. 다음 대사:"},
    ]


class Suggester:
    def __init__(self, model, effort, context_n, briefing):
        self.client = AsyncOpenAI()   # load_dotenv() 이후에 만들어야 키를 읽는다
        self.model = model
        self.effort = effort
        self.context_n = context_n
        self.briefing = briefing
        self.transcript = []      # [(speaker, text)]
        self.stopped_at = {}      # 화자별 발화종료 시각 — 반응속도의 t=0
        self.task = None
        self.first_token_ms = []
        self.stt_ms = []

    def on_event(self, speaker, kind, text):
        if kind == "stopped":
            self.stopped_at[speaker] = time.monotonic()
        elif kind == "drop":
            self.stopped_at.pop(speaker, None)
        elif kind == "completed":
            t0 = self.stopped_at.pop(speaker, None)
            self.transcript.append((speaker, text))
            print(f"\n[{LABELS[speaker]}] {text}")
            if speaker != "customer":
                return
            # 고객이 연달아 말하면 직전 제안은 이미 낡았다 — 취소하고 최신 맥락으로 다시.
            if self.task and not self.task.done():
                self.task.cancel()
            self.task = asyncio.create_task(self.suggest(t0))

    async def suggest(self, t0):
        if t0 is None:      # 발화종료 이벤트를 못 받은 경우(측정만 포기, 제안은 한다)
            t0 = time.monotonic()
        kwargs = {"max_completion_tokens": 300}
        if self.effort != "off":
            kwargs["reasoning_effort"] = self.effort

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=build_messages(self.transcript, self.briefing, self.context_n),
            stream=True,
            **kwargs,
        )
        first = None
        print("   💬 ", end="", flush=True)
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if not delta:
                continue
            if first is None:
                first = (time.monotonic() - t0) * 1000
            print(delta, end="", flush=True)

        total = (time.monotonic() - t0) * 1000
        if first is None:
            print("(빈 응답)", end="")
            first = total
        self.first_token_ms.append(first)
        print(f"\n   ⏱ 첫글자 {first:.0f}ms · 완료 {total:.0f}ms  (발화종료 기준)")

    def report(self):
        if not self.first_token_ms:
            print("\n제안 없음")
            return
        f = sorted(self.first_token_ms)
        print(f"\n{'─' * 60}\n제안 {len(f)}건 · 발화종료→첫글자: "
              f"평균 {statistics.mean(f):.0f}ms · 중앙 {statistics.median(f):.0f}ms · 최대 {f[-1]:.0f}ms")
        print(f"모델 {self.model} · effort {self.effort} · 최근 {self.context_n}발화")


async def main_async(args):
    briefing = args.briefing or ""
    if args.briefing_file:
        briefing = Path(args.briefing_file).read_text(encoding="utf-8").strip()

    if args.source:
        cap = FileCapture(args.source)
        speakers = ["customer"]     # 파일 모드는 전부 '고객' 채널로 흐른다
    else:
        cap = Capture(customer_device=find_device("USB Audio"), me_device=find_device("MacBook"))
        speakers = ["customer", "me"]

    s = Suggester(args.model, args.effort, args.context_n, briefing)
    print(f"모델 {args.model} · effort {args.effort} · 최근 {args.context_n}발화 "
          f"· 브리핑 {'있음' if briefing else '없음'}\n{'─' * 60}")
    try:
        await stt.run(cap, speakers, s.on_event)
        if s.task and not s.task.done():
            await asyncio.wait([s.task], timeout=10)   # 파일 끝: 마지막 제안 마무리 여유
    finally:
        cap.stop()
        s.report()


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--source", help="테스트용 wav (24kHz mono) — 없으면 실전 장치 모드")
    # gpt-4.1: V4 실측에서 속도·품질 모두 1위 (PLAN.md). gpt-5 계열은 느리고 만연체.
    p.add_argument("--model", default="gpt-4.1")
    p.add_argument("--effort", default="off",
                   help="추론 강도 (minimal/low/medium/high) · gpt-4.1 등 비추론 모델은 off")
    p.add_argument("--context-n", type=int, default=10, help="컨텍스트에 넣을 최근 발화 수")
    p.add_argument("--briefing", help="사전 브리핑 텍스트")
    p.add_argument("--briefing-file", help="사전 브리핑 파일 경로")
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
