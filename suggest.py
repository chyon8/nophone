"""제안 루프 v3 — 큐 생성 단일 루프 (2026-07-28 채점 제거).

고객 발화 종료 → 통화 전체 대화록을 컨텍스트로 키워드 큐 2~3개 스트리밍 + 반응속도(ms). 끝.

v2의 백그라운드 재채점(11섹션 채점표)은 **제거**했다. 채점표가 "빈 칸 = 다음 질문"으로 큐를
조종하면서 반복질문의 원인이 됐고(TUNING P1·P2·P8), 비용의 2/3를 먹었다. 통화 상태는
대화록 원본 하나뿐이다. 11섹션은 통화 끝 공고 draft의 템플릿(posting.py)으로만 남는다.

기준: 자연스러움 — 지금 파고들지/넘어갈지 판단이 맞는가. (지표 아님, 롤플레이로 체감 검증)

    uv run suggest.py --simulate "필라테스 스튜디오 대표, 회원관리 앱 원함"   # 역할 한 줄이면 시작
    uv run suggest.py --simulate sample/scenario_example.txt                # 상세 시나리오 파일도 가능
    uv run suggest.py --simulate "..." --voice                             # 매니저 대사를 마이크로(STT)
    uv run suggest.py --replay sample/replay_call.txt
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

import cost
import customer_sim
import posting
import stt
from capture import Capture, FileCapture, find_device  # 장치는 이름으로 찾는다 (USB 재연결 대비)

# 실통화(2026-07-13 전사)에서 확인된 절차만 적었다.
# TODO(사용자): 수수료 정책 등, 실제 안내 멘트 기준으로 보강할 것.
WISHKET_PROCESS = """[위시켓 절차 — 의뢰인이 물으면 이것만 근거로 답한다]
- 검수 후 공고 등록 → 개발사/개발자 지원 → 의뢰인이 마음에 드는 지원자를 골라 미팅 → 계약 진행.
- 공고 등록 전 의뢰인 이메일 인증 필요.
- 지원 파트너 조건: 업력 1년 이상, 보증보험 발급 가능."""

SYSTEM = f"""당신은 위시켓 매니저의 통화 코파일럿입니다.

상황: 매니저가 프로젝트 의뢰인과 전화 상담 중입니다. 목적은 프로젝트를 검수해서
위시켓에 개발자 모집 공고로 등록할 수 있을 만큼 정보를 확보하는 것입니다.

임무: 방금 의뢰인의 말이 끝났습니다. 매니저가 다음에 할 것을 **짧은 키워드 큐 2~3개**로,
우선순위 높은 순으로 주세요. 매니저는 전문가라 큐만 보면 자기 말로 바로 묻거나 답합니다.
완성된 문장을 읽어주는 게 아니라, "무엇을 물을지/짚을지"의 핵심만 던집니다.
매니저가 그중 하나를 골라 쓰므로, **서로 다른 각도로 2~3개**를 줍니다.

큐 고르는 순서(위일수록 우선):
1. 의뢰인이 방금 질문을 했다 → 답할 핵심을 1순위 큐로. 절차 관련은 [위시켓 절차]만 근거로 하고,
   거기 없는 정책(수수료 등)은 지어내지 말고 "확인 후 안내"로 한다.
2. 방금 답이 모호하거나 숫자·범위가 애매하다 → 확정해야 할 포인트.
3. 그 외 → [지금 물어야 할 것]의 상위 섹션들.

규칙:
- **키워드·개조식으로 짧게** (각 큐 대략 2~8단어). 완성 문장·존댓말·설명 금지.
- **2~3개를 각각 한 줄로** 출력한다. 서로 다른 각도 — 같은 걸 말만 바꾼 중복 금지.
- 방금 나온 새 정보(금액·수치·기능·고유명사)는 큐에 반영해 이어간다.
- [확보·처리 완료]에 이미 있는 내용은 다시 묻지 않는다.
- [직전 제안]과 같은 큐를 또 내지 않는다. 의뢰인이 그 질문에 답하지 않고 다른 말을
  했다면 되풀이하지 말고 다른 부족 항목으로 넘어간다.
- [사전 브리핑]은 통화 전 참고용 초기 정보일 뿐이다. 대화와 충돌하면 무조건 대화를 따른다 —
  브리핑에만 있고 대화에서 다르게 말한 내용을 전제로 큐를 만들지 않는다.
- 큐만 출력. 줄바꿈으로 구분. 따옴표·머리말·번호·불릿·설명 금지.

예)
예산 3천 상한 확정?
2단계 커머스 범위?
관리자 권한 구분?

{WISHKET_PROCESS}"""

AGENDA_SYSTEM = """당신은 위시켓 매니저의 통화 준비 도우미입니다.

곧 프로젝트 의뢰인과 전화 상담을 시작합니다. 목적은 이 프로젝트를 공고로 등록하고
개발사가 견적을 낼 수 있을 만큼 정보를 확보하는 것입니다.

임무: [사전 브리핑]을 근거로, 매니저가 통화에서 물어봐야 할 것들을 미리 뽑아 어젠다로 만듭니다.
구체적인 업무 범위 파악과 견적 산정에 필요한 질문 위주로, 브리핑에 이미 명확히 있는 내용은 빼고
비어 있거나 모호한 부분을 우선순위 높은 순으로 5~8개.

규칙:
- 각 항목은 짧은 키워드·개조식(대략 2~8단어). 완성 문장·존댓말·설명 금지. (통화 중 큐와 같은 톤)
- 브리핑에 이미 명확한 건 넣지 않는다. 부족·미확인 위주.
- [부족한 섹션]이 주어지면 그 순서를 우선 참고한다.
- 항목만 출력. 줄바꿈으로 구분. 번호·불릿·따옴표·머리말 금지.

예)
예산 상한·범위?
목표 출시 시점?
관리자 권한 구분?
결제 연동 필요?"""

LABELS = {"customer": "고객", "me": "나"}


def build_messages(transcript, briefing, context_n, last_suggestion=None):
    """큐 생성 컨텍스트. 채점표(중간 상태)를 쓰지 않고 대화록 원본을 그대로 본다
    (2026-07-28 사용자 지시로 채점 루프 제거 — 상태 머신이 반복질문의 원인이었다)."""
    system = SYSTEM
    glossary = stt.load_glossary_prompt()
    if glossary:
        system += f"\n\n{glossary}"

    blocks = []
    if briefing:
        blocks.append(f"[사전 브리핑 — 통화 전 등록 내용]\n{briefing}")
    if last_suggestion:
        blocks.append(f"[직전 제안 — 직전에 화면에 띄운 큐. 매니저가 실제로 읽었는지는 알 수 없음]\n{last_suggestion}")
    lines = transcript[-context_n:] if context_n else transcript   # 0이면 통화 전체
    recent = "\n".join(f"{LABELS[s]}: {t}" for s, t in lines)
    blocks.append(f"[지금까지 통화]\n{recent}\n\n방금 고객의 말이 끝났습니다. 다음 큐:")
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(blocks)}]


def _terminal_emit(kind, d):
    """기본(터미널) 싱크: emit 이벤트를 기존 print 출력으로 그대로 재현한다.
    server 등 다른 소비자는 emit 콜백을 주입해 같은 이벤트를 WS로 흘려보낸다."""
    if kind == "transcript":
        print(f"\n[{LABELS[d['speaker']]}] {d['text']}")
    elif kind == "suggest_start":
        print("   💬 ", end="", flush=True)
    elif kind == "suggest_delta":
        print(d["text"], end="", flush=True)
    elif kind == "suggest_done":
        print(f"\n   ⏱ 첫글자 {d['first_ms']:.0f}ms · 완료 {d['total_ms']:.0f}ms  (발화종료 기준)")
    elif kind == "agenda":
        print("\n📋 통화 전 어젠다 (미리 준비한 질문):")
        for i, q in enumerate(d["items"], 1):
            print(f"   {i}. {q}")
    elif kind == "usage":
        lat = f" {d['latency_ms']}ms" if d.get("latency_ms") is not None else ""
        print(f"   💰 {d['kind']} {d['prompt_tokens']}+{d['completion_tokens']}tok "
              f"(캐시 {d['cached_tokens']}) ${d['cost_usd']:.4f}{lat}")


class Suggester:
    def __init__(self, model, effort, context_n, briefing, emit=None, debounce_ms=1200):
        self.client = AsyncOpenAI()   # load_dotenv() 이후에 만들어야 키를 읽는다
        self.model = model
        self.effort = effort
        self.context_n = context_n
        self.briefing = briefing
        self.emit = emit or _terminal_emit
        self.transcript = []      # [(speaker, text)] — 통화 상태는 이것 하나뿐 (채점표 없음)
        self.stopped_at = {}      # 화자별 발화종료 시각 — 반응속도의 t=0
        self.task = None          # 큐 생성 태스크
        self.debounce_task = None # 발화 조각 병합 대기 (VAD 토막 방지)
        self.debounce_s = debounce_ms / 1000
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
            self.emit("transcript", {"speaker": speaker, "text": text})
            if speaker != "customer":
                return
            # VAD가 한 문장을 토막내면 completed가 여러 번 온다 (2026-07-26 진단).
            # 조각마다 제안하지 않도록, 마지막 조각 후 debounce 동안 잠잠하면 그때 한 번만 발사.
            if self.debounce_task and not self.debounce_task.done():
                self.debounce_task.cancel()
            if self.task and not self.task.done():
                self.task.cancel()          # 진행 중이던(낡은) 제안도 취소
            self.debounce_task = asyncio.create_task(self._debounced_fire(t0))

    async def _debounced_fire(self, t0):
        """마지막 고객 발화 조각 후 debounce_s 동안 새 조각이 없으면 최신 맥락으로 큐 생성."""
        try:
            await asyncio.sleep(self.debounce_s)
        except asyncio.CancelledError:
            return          # 고객이 이어 말함 → 다음 조각의 타이머로 넘어감
        self.task = asyncio.create_task(self.suggest(t0))

    async def drain(self):
        """진행 중인 debounce→큐 생성 태스크를 마무리한다 (replay·파일모드 종료용)."""
        if self.debounce_task and not self.debounce_task.done():
            try:
                await self.debounce_task
            except asyncio.CancelledError:
                pass
        for t in (self.task,):
            if t and not t.done():
                try:
                    await t
                except asyncio.CancelledError:
                    pass

    async def suggest(self, t0):
        if t0 is None:      # 발화종료 이벤트를 못 받은 경우(측정만 포기, 제안은 한다)
            t0 = time.monotonic()
        kwargs = {"max_completion_tokens": 300}
        if self.effort != "off":
            kwargs["reasoning_effort"] = self.effort

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=build_messages(self.transcript, self.briefing, self.context_n,
                                    self.last_suggestion),
            stream=True,
            stream_options={"include_usage": True},   # 마지막 청크에 usage 포함 → 비용 기록
            **kwargs,
        )
        first, parts, usage_chunk = None, [], None
        self.emit("suggest_start", {})
        async for chunk in stream:
            if getattr(chunk, "usage", None):
                usage_chunk = chunk                    # usage 전용 마지막 청크 (choices 비어있음)
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if not delta:
                continue
            if first is None:
                first = (time.monotonic() - t0) * 1000
            parts.append(delta)
            self.emit("suggest_delta", {"text": delta})
        if parts:
            self.last_suggestion = "".join(parts)
        else:
            self.emit("suggest_delta", {"text": "(빈 응답)"})

        total = (time.monotonic() - t0) * 1000
        if first is None:
            first = total
        self.first_token_ms.append(first)
        self.emit("suggest_done", {"first_ms": first, "total_ms": total, "text": "".join(parts)})
        self.emit("usage", cost.event("suggest", self.model, usage_chunk, total))

    async def agenda(self):
        """통화 전 어젠다: 브리핑으로 미리 물을 질문 5~8개를 1회 생성.
        대화 시작 전 콜드스타트 방어. 브리핑 없으면 생략."""
        if not self.briefing:
            return
        blocks = [f"[사전 브리핑]\n{self.briefing}"]
        t0 = time.monotonic()
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": AGENDA_SYSTEM},
                      {"role": "user", "content": "\n\n".join(blocks)}],
            max_completion_tokens=300,
        )
        self.emit("usage", cost.event("agenda", self.model, resp, (time.monotonic() - t0) * 1000))
        text = (resp.choices[0].message.content or "").strip()
        items = [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()]
        if items:
            self.emit("agenda", {"items": items})

    def report(self):
        if self.first_token_ms:
            f = sorted(self.first_token_ms)
            print(f"\n{'─' * 60}\n제안 {len(f)}건 · 발화종료→첫글자: "
                  f"평균 {statistics.mean(f):.0f}ms · 중앙 {statistics.median(f):.0f}ms · 최대 {f[-1]:.0f}ms")
            ctx = "통화 전체" if not self.context_n else f"최근 {self.context_n}발화"
            print(f"큐 {self.model}(effort {self.effort}) · 컨텍스트 {ctx}")
        else:
            print("\n제안 없음")

    async def make_draft(self) -> str:
        """지금까지의 대화록으로 공고 draft(마크다운)를 생성한다."""
        lines = [f"{LABELS[s]}: {t}" for s, t in self.transcript]
        t0 = time.monotonic()
        text, resp = await posting.generate(self.client, self.model, self.briefing, lines, None)
        if resp is not None:
            self.emit("usage", cost.event("posting", self.model, resp, (time.monotonic() - t0) * 1000))
        return text

    async def print_draft(self):
        """통화 끝에 공고 draft를 출력한다."""
        if not self.transcript:
            return
        print(f"\n{'═' * 60}\n📋 공고 draft\n{'═' * 60}")
        print(await self.make_draft())


async def replay(path, s):
    """대화록 텍스트를 화자 라벨대로 한 줄씩 흘려 제안·채점 품질만 본다 (오디오·전화 없이).
    파일 형식: 한 줄에 `고객: ...` 또는 `나: ...`. STT를 거치지 않으므로 ms는 LLM 구간만이다.
    실제 순서대로: 대사 생성이 먼저(직전 점수표 사용), 재채점이 그 뒤."""
    s.debounce_s = 0     # 한 줄=온전한 발화라 조각 병합 불필요
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
        await s.drain()


def load_scenario(arg):
    """시나리오: 파일 경로면 읽고, 아니면 그 문자열이 곧 역할이다.
    ("필라테스 스튜디오 대표, 회원관리 앱 원함" 처럼 한 줄만 줘도 AI 고객이 알아서 살을 붙인다)"""
    p = Path(arg)
    return p.read_text(encoding="utf-8").strip() if p.is_file() else arg.strip()


async def simulate(scenario, s, customer_model):
    """전화기 없이 AI 고객을 상대로 '타이핑 통화'를 돌린다.
    매니저(사용자)가 대사를 입력하면 → AI 고객이 역할대로 반응 → 그 고객 턴이
    큐 생성 파이프라인(on_event)을 그대로 트리거한다. 마이크·STT 없음."""
    s.debounce_s = 0     # 타이핑/텍스트 턴은 온전한 발화라 조각 병합 불필요
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
        t0 = time.monotonic()
        reply, resp = await customer_sim.respond(s.client, customer_model, scenario, lines)
        s.emit("usage", cost.event("customer_sim", customer_model, resp,
                                   (time.monotonic() - t0) * 1000))

        # 진짜 고객 발화처럼 기존 파이프라인에 흘려보냄 → 큐(💬)
        s.on_event("customer", "stopped", None)
        s.on_event("customer", "completed", reply)
        await s.drain()
    s.report()
    await s.print_draft()


async def simulate_voice(scenario, s, customer_model):
    """음성 롤플레이: 맥북 마이크로 매니저(사용자)가 말하면 STT가 받고 → AI 고객이 텍스트로 반응.
    타이핑 대신 실전과 같은 '말하기'를 예행연습한다. on_event를 감싸 'me' 확정 턴마다 고객을 주입."""
    loop = asyncio.get_running_loop()
    persona = {"me": "매니저", "customer": "나"}   # 고객 관점 라벨

    async def inject_customer():
        lines = [f"{persona[sp]}: {t}" for sp, t in s.transcript]
        t0 = time.monotonic()
        reply, resp = await customer_sim.respond(s.client, customer_model, scenario, lines)
        s.emit("usage", cost.event("customer_sim", customer_model, resp,
                                   (time.monotonic() - t0) * 1000))
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

    s = Suggester(args.model, args.effort, args.context_n, briefing,
                  debounce_ms=args.debounce_ms)
    ctx = "통화 전체" if not args.context_n else f"최근 {args.context_n}발화"
    print(f"큐 {args.model}(effort {args.effort}) · 컨텍스트 {ctx} "
          f"· 브리핑 {'있음' if briefing else '없음'}")
    if briefing:      # 통화 전 어젠다 — 미리 물을 것 준비하고 시작
        await s.agenda()
    print("─" * 60)

    if args.replay:
        await replay(args.replay, s)
        s.report()
        await s.print_draft()
        return

    if args.simulate:
        scenario = load_scenario(args.simulate)
        if args.voice:
            await simulate_voice(scenario, s, args.customer_model)
        else:
            await simulate(scenario, s, args.customer_model)
        return

    if args.source:
        cap = FileCapture(args.source)
        speakers = ["customer"]     # 파일 모드는 전부 '고객' 채널로 흐른다
    else:
        cap = Capture(customer_device=find_device("USB Audio"), me_device=find_device("MacBook"))
        speakers = ["customer", "me"]
    try:
        await stt.run(cap, speakers, s.on_event)
        try:      # 파일 끝: 마지막 debounce·큐 생성 마무리 여유
            await asyncio.wait_for(s.drain(), timeout=15)
        except asyncio.TimeoutError:
            pass
    finally:
        cap.stop()
        s.report()
    await s.print_draft()


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--source", help="테스트용 wav (24kHz mono) — 없으면 실전 장치 모드")
    p.add_argument("--replay", help="대화록 텍스트(`고객:`/`나:`) 재생 — 전화 없이 품질만 검증")
    p.add_argument("--simulate", help="롤플레이 시뮬: AI 고객 상대로 통화. "
                                      "역할 한 줄(\"필라테스 대표, 예약앱 원함\") 또는 시나리오 파일 경로")
    p.add_argument("--voice", action="store_true", help="시뮬 모드에서 매니저 대사를 타이핑 대신 마이크로 말하기(STT)")
    p.add_argument("--customer-model", default="gpt-4.1", help="시뮬 모드 AI 고객 모델")
    # gpt-4.1: V4 실측에서 속도·품질 모두 1위 (PLAN.md). gpt-5 계열은 느리고 만연체.
    p.add_argument("--model", default="gpt-4.1")
    p.add_argument("--effort", default="off",
                   help="추론 강도 (minimal/low/medium/high) · gpt-4.1 등 비추론 모델은 off")
    p.add_argument("--context-n", type=int, default=0,
                   help="컨텍스트에 넣을 최근 발화 수 (0=통화 전체, 기본)")
    p.add_argument("--debounce-ms", type=int, default=1200,
                   help="고객 발화 조각 병합 대기(ms) — VAD 토막 방지. replay/simulate는 자동 0")
    p.add_argument("--briefing", help="사전 브리핑 텍스트")
    p.add_argument("--briefing-file", help="사전 브리핑 파일 경로")
    args = p.parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
