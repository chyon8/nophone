"""AI 고객 시뮬레이터 (HANDOFF.md 2026-07-21 'B(타이핑)' 모드).

전화기 없이 제안 엔진의 상호작용 품질을 검증하려고, 매니저(사용자)의 말에 반응하는
'의뢰인' 역을 LLM에게 시킨다. 시나리오(프로젝트 진실+페르소나)를 근거로만 답하고,
정보를 한 번에 다 쏟지 않아 replay(고정 대본)로는 못 보던 반응형 대화를 만든다.
"""
from openai import AsyncOpenAI  # noqa: F401 (타입 힌트용, 실제 client는 호출부에서 주입)

SYSTEM = """당신은 위시켓에 IT 프로젝트를 등록한 '의뢰인'입니다. 지금 위시켓 매니저와 전화 상담 중입니다.

아래 [프로젝트 진실]이 당신이 실제로 원하는 것의 전부입니다. 이걸 근거로 매니저의 방금 말에 답하세요.

의뢰인답게 굴기:
- 정보를 한 번에 다 쏟지 마세요. 매니저가 물은 것에만, 실제 사람처럼 답합니다.
- 가끔 모호하게 답하거나("글쎄요, 예산은 아직 정확히는...") 되물어도 됩니다("그건 어떻게 되는 거예요?").
- 절차·수수료 같은 위시켓 내부 정책은 의뢰인인 당신은 잘 모릅니다. 모르면 모른다고 하거나 매니저에게 되물으세요.
- [프로젝트 진실]에 없는 사소한 건 의뢰인이 즉석에서 정할 법한 선에서 자연스럽게. 진실과 어긋나게 지어내지는 마세요.
- 1~3문장, 전화 구어체 존댓말. 대사만 출력 (따옴표·머리말·설명 금지)."""


async def respond(client, model, scenario, transcript_lines):
    """시나리오와 지금까지 대화를 근거로 의뢰인의 다음 대사 1개를 만든다.

    transcript_lines: 고객 관점으로 라벨링된 대화록. 매니저 발화는 "매니저: ...",
    의뢰인(=본인) 발화는 "나: ..." 형식으로 넘긴다.
    """
    user = (f"[프로젝트 진실 — 당신이 원하는 것]\n{scenario}\n\n"
            f"[지금까지 통화]\n" + "\n".join(transcript_lines) +
            "\n\n매니저의 방금 말에 대한 당신(의뢰인)의 답:")
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": user}],
        max_completion_tokens=200,
    )
    return (resp.choices[0].message.content or "").strip()
