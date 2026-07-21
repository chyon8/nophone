"""제안 루프 v2 (청크 D 프로토타입): SCORING_SPEC.md 기준 2루프 구조 (DESIGN.md "제안 엔진").

- 빠른 루프: 고객 발화 종료 → 섹션 상태+최근 대화를 컨텍스트로 "다음 대사" 1개 스트리밍 + 반응속도(ms)
- 느린 루프: 백그라운드에서 대화록 재채점 → 12섹션 confidence 갱신 (scoring.py)
- 통화 전: --briefing(-file)의 초기 등록 내용을 1회 채점하고 시작 (뭐가 비었는지 알고 시작)

DESIGN.md 성공 기준: 1순위 품질(그대로 읽을 수 있는 대사) · 2순위 속도(발화종료→첫글자 2~3초 이내)

    uv run suggest.py --replay sample/replay_call.txt --briefing-file sample/briefing_example.txt
    uv run suggest.py --simulate sample/scenario_example.txt --briefing-file sample/briefing_coreline.txt          # AI 고객 상대 타이핑 통화 (브리핑 권장 — 없으면 콜드스타트 환각)
    uv run suggest.py --simulate sample/scenario_example.txt --briefing-file sample/briefing_coreline.txt --voice  # 위와 같되 매니저 대사는 마이크로 말하기(STT)
    uv run suggest.py --source sample/test_call_60s.wav      # 녹취 1배속 (STT 포함)
    uv run suggest.py --briefing-file briefing.txt           # 실전 통화 (장치 자동 탐색)
"""
import argparse
import asyncio
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

import customer_sim
import scoring
import stt
from capture import Capture, FileCapture
from server import find_device  # 장치는 번호가 아니라 이름으로 찾는다 (USB 재연결 대비)

# 실통화(2026-07-13 전사)에서 확인된 절차만 적었다.
# TODO(사용자): 수수료 정책 등, 실제 안내 멘트 기준으로 보강할 것.
WISHKET_PROCESS = """[위시켓 절차 — 의뢰인이 물으면 이것만 근거로 답한다]
- 검수 후 공고 등록 → 개발사/개발자 지원 → 의뢰인이 마음에 드는 지원자를 골라 미팅 → 계약 진행.
- 공고 등록 전 의뢰인 이메일 인증 필요.
- 지원 파트너 조건: 업력 1년 이상, 보증보험 발급 가능."""

SYSTEM = f"""당신은 위시켓 매니저의 통화 코파일럿입니다.

상황: 매니저가 프로젝트 의뢰인과 전화 상담 중입니다. 목적은 프로젝트를 검수해서
위시켓에 개발자 모집 공고로 등록할 수 있을 만큼 정보를 확보하는 것입니다.

임무: 방금 의뢰인의 말이 끝났습니다. 매니저가 **그대로 소리내어 읽을** 다음 대사를 하나만 쓰세요.

대사 고르는 순서:
1. 의뢰인이 방금 질문을 했다 → 답하는 대사. 절차 관련은 [위시켓 절차]만 근거로 답하고,
   거기 없는 정책(수수료 등)은 지어내지 말고 "확인해서 안내드리겠다"는 대사로 한다.
2. 방금 답이 모호하거나 숫자·범위가 애매하다 → 짧게 되물어 확정하는 대사.
3. 그 외 → [지금 물어야 할 것]의 1순위 섹션을 겨냥한 질문 대사.

규칙:
- 조언("~라고 물어보세요") 금지. 바로 읽을 대사만.
- 1~2문장, 전화 구어체 존댓말. 질문은 **반드시 한 번에 하나만** — 두 가지를 묶어 묻지 않는다.
- 방금 들은 말에 새 정보(금액·수치·기능·고유명사)가 있으면 짧게 받아 확인하고 잇는다.
- [확보 현황]에 이미 있는 내용은 다시 묻지 않는다.
- [직전 제안]과 같은 질문을 또 만들지 않는다. 의뢰인이 그 질문에 답하지 않고 다른 말을
  했다면 같은 걸 되풀이하지 말고, 방금 말을 받아준 뒤 다른 부족 항목으로 넘어간다.
- 대사만 출력. 따옴표·머리말·설명 금지.

{WISHKET_PROCESS}"""

LABELS = {"customer": "고객", "me": "나"}


def build_messages(transcript, briefing, context_n, sections, last_suggestion=None):
    system = SYSTEM
    glossary = stt.load_glossary_prompt()
    if glossary:
        system += f"\n\n{glossary}"

    blocks = []
    if briefing:
        blocks.append(f"[사전 브리핑 — 통화 전 등록 내용]\n{briefing}")
    if sections:
        known = [f"- {scoring.KO[k]}: {v['evidence']}" for k, v in sections.items()
                 if v["confidence"] >= 50]
        if known:
            blocks.append("[확보 현황 — 이미 아는 것, 재질문 금지]\n" + "\n".join(known))
        gaps = [f"{i}. {scoring.KO[k]} (확보도 {conf}) — 지금까지: {sections[k]['evidence']}"
                for i, (k, _, conf) in enumerate(scoring.priorities(sections)[:3], 1)]
        if gaps:
            blocks.append("[지금 물어야 할 것 — 부족한 순]\n" + "\n".join(gaps))
    if last_suggestion:
        blocks.append(f"[직전 제안 — 직전에 화면에 띄운 대사. 매니저가 실제로 읽었는지는 알 수 없음]\n{last_suggestion}")
    recent = "\n".join(f"{LABELS[s]}: {t}" for s, t in transcript[-context_n:])
    blocks.append(f"[최근 대화]\n{recent}\n\n방금 고객의 말이 끝났습니다. 다음 대사:")
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(blocks)}]


class Suggester:
    def __init__(self, model, effort, context_n, briefing, scorer_model):
        self.client = AsyncOpenAI()   # load_dotenv() 이후에 만들어야 키를 읽는다
        self.model = model
        self.effort = effort
        self.context_n = context_n
        self.briefing = briefing
        self.scorer_model = scorer_model
        self.transcript = []      # [(speaker, text)] — 원본 기억
        self.sections = None      # 12섹션 채점표 — 구조화된 기억 (통화 메모리)
        self.stopped_at = {}      # 화자별 발화종료 시각 — 반응속도의 t=0
        self.task = None          # 빠른 루프 (대사 생성)
        self.score_task = None    # 느린 루프 (재채점)
        self.last_suggestion = None   # 직전 제안 — 같은 질문 반복 방지용
        self.first_token_ms = []

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
            # 느린 루프: 대사 생성을 막지 않고 백그라운드에서 점수표 갱신
            if self.score_task and not self.score_task.done():
                self.score_task.cancel()
            self.score_task = asyncio.create_task(self.rescore())

    async def suggest(self, t0):
        if t0 is None:      # 발화종료 이벤트를 못 받은 경우(측정만 포기, 제안은 한다)
            t0 = time.monotonic()
        kwargs = {"max_completion_tokens": 300}
        if self.effort != "off":
            kwargs["reasoning_effort"] = self.effort

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=build_messages(self.transcript, self.briefing, self.context_n,
                                    self.sections, self.last_suggestion),
            stream=True,
            **kwargs,
        )
        first, parts = None, []
        print("   💬 ", end="", flush=True)
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if not delta:
                continue
            if first is None:
                first = (time.monotonic() - t0) * 1000
            parts.append(delta)
            print(delta, end="", flush=True)
        if parts:
            self.last_suggestion = "".join(parts)

        total = (time.monotonic() - t0) * 1000
        if first is None:
            print("(빈 응답)", end="")
            first = total
        self.first_token_ms.append(first)
        print(f"\n   ⏱ 첫글자 {first:.0f}ms · 완료 {total:.0f}ms  (발화종료 기준)")

    async def rescore(self):
        lines = [f"{LABELS[s]}: {t}" for s, t in self.transcript]
        res = await scoring.score(self.client, self.scorer_model, self.briefing, lines)
        if res is None:
            print("   ⚠️ 채점 실패 — 이전 점수표 유지")
            return
        self.sections = res
        comp = scoring.completion(res)
        tops = " ".join(f"{scoring.KO[k]}({conf})" for k, _, conf in scoring.priorities(res)[:3])
        close = "종료 가능 ✅" if scoring.can_close(res) else "종료 불가"
        print(f"   📊 완성도 {comp}% {scoring.grade(comp)} · 부족: {tops} · {close}")

    def report(self):
        if self.first_token_ms:
            f = sorted(self.first_token_ms)
            print(f"\n{'─' * 60}\n제안 {len(f)}건 · 발화종료→첫글자: "
                  f"평균 {statistics.mean(f):.0f}ms · 중앙 {statistics.median(f):.0f}ms · 최대 {f[-1]:.0f}ms")
            print(f"대사 {self.model}(effort {self.effort}) · 채점 {self.scorer_model} "
                  f"· 최근 {self.context_n}발화")
        else:
            print("\n제안 없음")
        if self.sections:
            comp = scoring.completion(self.sections)
            print(f"\n[최종 채점] 완성도 {comp}% {scoring.grade(comp)} · "
                  f"{'상담 종료 가능 ✅' if scoring.can_close(self.sections) else '종료 조건 미충족'}")
            for k in scoring.WEIGHTS:
                sec = self.sections[k]
                print(f"  {sec['confidence']:3d}  {scoring.KO[k]:14s} {sec['evidence'][:56]}")


async def replay(path, s):
    """대화록 텍스트를 화자 라벨대로 한 줄씩 흘려 제안·채점 품질만 본다 (오디오·전화 없이).
    파일 형식: 한 줄에 `고객: ...` 또는 `나: ...`. STT를 거치지 않으므로 ms는 LLM 구간만이다.
    실제 순서대로: 대사 생성이 먼저(직전 점수표 사용), 재채점이 그 뒤."""
    speaker_of = {v: k for k, v in LABELS.items()}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        label, text = line.split(":", 1)
        speaker = speaker_of.get(label.strip())
        if not speaker:
            continue
        s.on_event(speaker, "stopped", None)
        s.on_event(speaker, "completed", text.strip())
        if s.task and not s.task.done():
            await s.task
        if s.score_task and not s.score_task.done():
            await s.score_task


async def simulate(path, s, customer_model):
    """전화기 없이 AI 고객을 상대로 '타이핑 통화'를 돌린다 (HANDOFF.md 2026-07-21 B 모드).
    매니저(사용자)가 대사를 입력하면 → AI 고객이 시나리오대로 반응 → 그 고객 턴이
    기존 제안·채점 파이프라인(on_event)을 그대로 트리거한다. 마이크·STT 없음."""
    scenario = Path(path).read_text(encoding="utf-8").strip()
    loop = asyncio.get_running_loop()
    persona = {"me": "매니저", "customer": "나"}   # 고객 관점 라벨 (매니저=상대, 나=의뢰인 본인)
    print("롤플레이 시뮬 시작 — 매니저 대사를 입력하세요. 빈 줄 또는 /quit 로 종료.\n")
    while True:
        try:
            line = await loop.run_in_executor(None, input, "나(매니저) > ")
        except EOFError:
            break
        line = line.strip()
        if not line or line == "/quit":
            break
        s.on_event("me", "completed", line)   # 대화록에 '나' 턴 추가 (+화면 표시)

        # AI 고객 반응 — 시나리오 근거, 지금까지 대화를 고객 관점으로 넘김
        lines = [f"{persona[sp]}: {t}" for sp, t in s.transcript]
        reply = await customer_sim.respond(s.client, customer_model, scenario, lines)

        # 진짜 고객 발화처럼 기존 파이프라인에 흘려보냄 → 제안(💬) + 백그라운드 재채점(📊)
        s.on_event("customer", "stopped", None)
        s.on_event("customer", "completed", reply)
        if s.task and not s.task.done():
            await s.task
        if s.score_task and not s.score_task.done():
            await s.score_task
    s.report()


async def simulate_voice(path, s, customer_model):
    """음성 롤플레이: 맥북 마이크로 매니저(사용자)가 말하면 STT가 받고 → AI 고객이 텍스트로 반응.
    타이핑 대신 실전과 같은 '말하기'를 예행연습한다. on_event를 감싸 'me' 확정 턴마다 고객을 주입."""
    scenario = Path(path).read_text(encoding="utf-8").strip()
    loop = asyncio.get_running_loop()
    persona = {"me": "매니저", "customer": "나"}   # 고객 관점 라벨

    async def inject_customer():
        lines = [f"{persona[sp]}: {t}" for sp, t in s.transcript]
        reply = await customer_sim.respond(s.client, customer_model, scenario, lines)
        s.on_event("customer", "stopped", None)
        s.on_event("customer", "completed", reply)   # 기존 제안·채점 파이프라인 트리거

    def on_event(speaker, kind, text):
        s.on_event(speaker, kind, text)              # 대화록·제안·채점은 기존 그대로
        if speaker == "me" and kind == "completed":  # 매니저 발화 확정 → AI 고객 반응 주입
            loop.create_task(inject_customer())

    print("음성 롤플레이 시작 — 마이크에 매니저 대사를 말하세요. AI 고객이 텍스트로 답합니다. Ctrl+C 로 종료.\n")
    cap = Capture(customer_device=None, me_device=find_device("MacBook"))
    try:
        await stt.run(cap, ["me"], on_event)
    finally:
        cap.stop()
        s.report()


async def main_async(args):
    briefing = args.briefing or ""
    if args.briefing_file:
        briefing = Path(args.briefing_file).read_text(encoding="utf-8").strip()

    s = Suggester(args.model, args.effort, args.context_n, briefing, args.scorer_model)
    print(f"대사 {args.model}(effort {args.effort}) · 채점 {args.scorer_model} "
          f"· 최근 {args.context_n}발화 · 브리핑 {'있음' if briefing else '없음'}")
    if briefing:      # 통화 전 1회 채점 — 뭐가 비었는지 알고 시작
        print("사전 브리핑 채점 중...")
        await s.rescore()
    print("─" * 60)

    if args.replay:
        await replay(args.replay, s)
        s.report()
        return

    if args.simulate:
        if args.voice:
            await simulate_voice(args.simulate, s, args.customer_model)
        else:
            await simulate(args.simulate, s, args.customer_model)
        return

    if args.source:
        cap = FileCapture(args.source)
        speakers = ["customer"]     # 파일 모드는 전부 '고객' 채널로 흐른다
    else:
        cap = Capture(customer_device=find_device("USB Audio"), me_device=find_device("MacBook"))
        speakers = ["customer", "me"]
    try:
        await stt.run(cap, speakers, s.on_event)
        pending = [t for t in (s.task, s.score_task) if t and not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=15)   # 파일 끝: 마지막 제안·채점 마무리 여유
    finally:
        cap.stop()
        s.report()


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--source", help="테스트용 wav (24kHz mono) — 없으면 실전 장치 모드")
    p.add_argument("--replay", help="대화록 텍스트(`고객:`/`나:`) 재생 — 전화 없이 품질만 검증")
    p.add_argument("--simulate", help="롤플레이 시뮬: AI 고객 상대로 통화 (시나리오 파일 경로)")
    p.add_argument("--voice", action="store_true", help="시뮬 모드에서 매니저 대사를 타이핑 대신 마이크로 말하기(STT)")
    p.add_argument("--customer-model", default="gpt-4.1", help="시뮬 모드 AI 고객 모델")
    # gpt-4.1: V4 실측에서 속도·품질 모두 1위 (PLAN.md). gpt-5 계열은 느리고 만연체.
    p.add_argument("--model", default="gpt-4.1")
    p.add_argument("--effort", default="off",
                   help="추론 강도 (minimal/low/medium/high) · gpt-4.1 등 비추론 모델은 off")
    p.add_argument("--scorer-model", default="gpt-4.1",
                   help="느린 루프(재채점) 모델 — 백그라운드라 속도보다 정확도 우선")
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
