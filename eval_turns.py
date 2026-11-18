"""턴 단위 평가 (DESIGN.md 2026-11-17 개정 (2)) — 실제 통화 녹취의 고객 말마다
AI 질문 제안 · AI 답변 제안 · 실제 매니저 말을 나란히 놓고, AI 판정기가 먼저 표시한다.

목표: 컨설팅을 모르는 사람이 이 제안만 보고 통화할 수 있는가. 가장 중요한 건
"질문을 적절히 생성하는가", "답변을 적절히 제안하는가".

- 판정기(LLM)가 먼저 표시하고, 사람은 ⚠ 표시된 곳과 애매한 곳만 본다(사람 판정칸 있음).
  판정기도 틀릴 수 있으니 처음 몇 번은 판정기 자체를 사람이 같이 검사할 것.
- 튜닝용/시험용: 통화 ID 해시로 고정 배정(약 30%가 시험용). 녹취가 새로 들어와도 배정이 안 바뀐다.
  튜닝은 tune에서만, 성적은 test로 확인 — 튜닝에 쓴 녹취에서만 좋아 보이는 착시 방지.
- 맥락 정리: 고객이 길게 말하는 중간의 매니저 맞장구("네", "음")는 빼고 고객 말을 한 덩어리로 합친다
  (라이브 디바운스와 같은 효과). 평가 시점은 고객 말이 끝나고 매니저가 실제로 대꾸한 순간뿐이다.
- 엔진: 지금 suggest.py의 질문 큐(SYSTEM + 통화 전 어젠다)와 제안 답변(ANSWER_SYSTEM) 그대로.
  직전 제안(반복 방지)은 쓰지 않는다 — 턴마다 독립 병렬 실행.
- 결과는 실제 고객 내용이라 sample/review/ (gitignore)에만 쓴다.

    uv run convert_calls.py ~/Desktop/call-samples/*.md sample/calls   # 먼저 변환
    uv run eval_turns.py sample/calls --dry-run                          # 건수·배정만 (API 안 씀)
    uv run eval_turns.py sample/calls --set tune --limit 2 --name try   # 2건만 시험
    uv run eval_turns.py sample/calls --set tune --name baseline        # 튜닝용 전체
"""
import argparse
import asyncio
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

import cost
import suggest

BACKCHANNEL = {"네", "예", "음", "아", "어", "응", "오", "네네", "네네네", "예예", "예예예", "그렇죠",
               "그렇군요", "맞아요", "맞습니다", "알겠습니다", "이해했습니다", "그러시군요", "아하"}

JUDGE_SYSTEM = """당신은 위시켓 검수 통화 코파일럿의 엄격한 평가자입니다.

상황: 위시켓 매니저(경력자)가 IT 외주 프로젝트 의뢰인과 검수 통화를 했습니다. 고객 말이 끝날 때마다
AI가 (1) 다음에 물을 질문 큐와 (2) 고객 질문에 대한 제안 답변을 냈습니다.
이 AI는 앞으로 컨설팅 경험이 없는 사람이 보고 그대로 쓰게 됩니다. 기준은 하나:
"비전문가가 이 제안만 보고 다음 말을 했을 때, 실제 매니저만큼 통화가 잘 흘러가는가."
후하게 주지 마세요. 애매하면 낮은 쪽으로 판정합니다.

판정 1 — q (질문 큐, 2-3개 중 가장 나은 것 기준):
- "same": 실제 매니저가 바로 이어서(다음 1-2턴) 물은 것과 같은 정보를 묻는 큐가 있다. 큐는 키워드 형식이므로
  표현이 짧아도 묻는 정보가 같으면 same이다. 주제만 비슷하고 묻는 정보가 다르면 same이 아니다
  (매니저는 "결제는 카드만 받으세요?", 큐는 "결제 기능 우선순위" → same 아님).
- "good": 매니저와 다르지만, 방금 고객 말에 바로 이어지고 아직 안 나온 정보를 구체적으로 묻는 질문이라
  매니저 질문만큼 유용하다.
- "weak": 틀리진 않지만 일반적·추상적이다("주요 업무 프로세스 상세", "필수 vs 선택 기능 구분",
  "데이터 이관 범위"처럼 아무 통화에나 붙는 질문). 또는 방금 고객 말과 연결이 약하다.
  비전문가가 받아서 바로 쓰기 어렵다.
- "bad": 이미 대화·등록 내용에 나온 걸 다시 묻거나, 맥락에 안 맞거나, 엉뚱하다.
- "na": 질문할 차례가 아니다 — 인사, 통화 마무리, 또는 고객이 물어서 답부터 해야 하는 순간.

판정 2 — asked (고객이 방금 답을 원했나): true / false
말끝이 질문 꼴이 아니어도 답을 원하는 뜻이면 true다.
- "키오스크까지 한다 치면"(그러면 얼마냐), "그럼 500이면 되나요?", "얼마나 걸려요?", "이런 것도 되나요?",
  "렌탈하는 업체도 있던데요"(그쪽과 비교하면 어떠냐), "어느 정도일지 가늠이 안 되죠"(얼마쯤 드냐).
- 고객이 금액·기간을 궁금해하거나 가늠이 안 된다고 하면 견적을 물은 것이다.
- 실제 매니저가 이어서 금액·기간·가능 여부·기술 설명을 답했다면 고객이 그걸 물었을 가능성이 크다.
- 대상: 기술, 서비스·솔루션, 견적(금액·기간), 가능 여부. 위시켓 절차·수수료·계약·이메일 인증·연락 방법은
  대상이 아니다(false).
ask_what: asked가 true면 무엇을 물었는지 짧게, 아니면 빈 문자열.

판정 3 — a (AI 제안 답변의 정확성, asked가 true이고 AI 답이 있을 때만. 그 외엔 "na"):
- "correct": 사실상 맞고 비전문가가 바로 말할 수 있다.
- "better": 실제 매니저 답보다 정확하거나 유용하다.
- "wrong": 틀렸거나, 지어냈거나, 고객에게 그대로 말하면 위험하다.

reason: 판정 이유 한 줄(한국어, 40자 안팎). 특히 weak·bad·wrong은 무엇이 문제인지.

JSON 하나만. q는 same/good/weak/bad/na 중 하나, a는 correct/better/wrong/na 중 하나(라벨 단어만):
{"q": "weak", "asked": true, "ask_what": "키오스크 추가 시 금액", "a": "na", "reason": "..."}"""

Q_LABELS = ("same", "good", "weak", "bad", "na")
A_LABELS = ("correct", "better", "wrong", "missed", "extra", "na")


def split_of(call_id):
    return "test" if int(hashlib.sha1(call_id.encode()).hexdigest(), 16) % 10 < 3 else "tune"


def is_backchannel(text):
    words = re.findall(r"[가-힣]+", text)
    return 0 < len(words) <= 6 and all(w in BACKCHANNEL for w in words)


def load_dialog(path):
    """replay 형식 → [(speaker, text)]. 고객 말 사이에 낀 매니저 맞장구는 빼고 고객 말을 합친다."""
    speaker_of = {v: k for k, v in suggest.LABELS.items()}
    raw = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        label, sep, text = line.strip().partition(":")
        sp = speaker_of.get(label.strip())
        if sep and sp and text.strip():
            raw.append((sp, text.strip()))
    dialog = []
    for k, (sp, t) in enumerate(raw):
        if (sp == "me" and is_backchannel(t) and 0 < k < len(raw) - 1
                and raw[k - 1][0] == "customer" and raw[k + 1][0] == "customer"):
            continue
        if dialog and dialog[-1][0] == sp:
            dialog[-1] = (sp, dialog[-1][1] + " " + t)
        else:
            dialog.append((sp, t))
    return dialog


def fmt(turns):
    return "\n".join(f"{suggest.LABELS[s]}: {t}" for s, t in turns)


async def make_agenda(client, model, briefing):
    """라이브와 같게: 통화 전 브리핑으로 어젠다 1회 생성 (Suggester.agenda와 같은 프롬프트)."""
    if not briefing:
        return [], 0.0
    resp = await client.chat.completions.create(
        model=model, max_completion_tokens=300,
        messages=[{"role": "system", "content": suggest.AGENDA_SYSTEM},
                  {"role": "user", "content": f"[사전 브리핑]\n{briefing}"}])
    text = (resp.choices[0].message.content or "").strip()
    items = [ln.strip(" -•\t") for ln in text.splitlines() if ln.strip()]
    return items, cost.event("agenda", model, resp)["cost_usd"]


async def make_cue(client, model, dialog, briefing, agenda):
    t0 = time.monotonic()
    resp = await client.chat.completions.create(
        model=model, max_completion_tokens=300,
        messages=suggest.build_messages(dialog, briefing, 0, None, agenda))
    return (resp.choices[0].message.content or "").strip(), cost.event(
        "suggest", model, resp, (time.monotonic() - t0) * 1000)


async def judge(client, model, dialog, i, briefing, cue, ans):
    user = "\n\n".join([
        f"[등록 내용 — 통화 전]\n{briefing[:1500] or '(없음)'}",
        f"[직전 대화]\n{fmt(dialog[max(0, i - 8):i]) or '(통화 시작)'}",
        f"[방금 고객 말]\n{dialog[i][1]}",
        f"[AI 질문 큐]\n{cue or '(없음)'}",
        f"[AI 제안 답변]\n{ans['answer'] if ans else '(없음)'}",
        f"[실제로 이어진 대화 — 나=매니저]\n{fmt(dialog[i + 1:i + 5]) or '(통화 끝)'}",
        "JSON:"])
    resp = await client.chat.completions.create(
        model=model, max_completion_tokens=200, response_format={"type": "json_object"},
        temperature=0,   # 같은 입력엔 같은 판정 — 판정기 흔들림이 엔진 비교를 가리지 않게
        messages=[{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}])
    try:
        d = json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        d = {}
    asked = bool(d.get("asked"))
    # 놓침·불필요는 판정기에 맡기지 않고 "물었나" + "답이 있나"로 코드가 정한다
    if asked and ans:
        a = d.get("a") if d.get("a") in ("correct", "better", "wrong") else "?"
    elif asked:
        a = "missed"
    else:
        a = "extra" if ans else "na"
    q = d.get("q") if d.get("q") in Q_LABELS else "?"
    return ({"q": q, "asked": asked, "ask_what": d.get("ask_what", ""), "a": a,
             "reason": d.get("reason", "")},
            cost.event("judge", model, resp)["cost_usd"])


def flagged(row):
    return row["judge"]["q"] == "bad" or row["judge"]["a"] in ("wrong", "missed")


def write_call_md(outdir, cid, split, dialog, agenda, rows, total_cost):
    qc = Counter(r["judge"]["q"] for r in rows)
    ac = Counter(r["judge"]["a"] for r in rows)
    flags = [r["turn"] for r in rows if flagged(r)]
    out = [f"# {cid} — 턴 평가 ({split})", "",
           f"고객 말 {len(rows)}곳 · 비용 ${total_cost:.2f}", "",
           "질문 판정: " + " / ".join(f"{k} {qc[k]}" for k in Q_LABELS), "",
           "답변 판정: " + " / ".join(f"{k} {ac[k]}" for k in A_LABELS), "",
           "⚠ 먼저 볼 곳(질문 bad · 답변 wrong/missed): " + (" ".join(f"[{t}]" for t in flags) or "없음"), "",
           "`사람 판정:` 뒤에 ○(판정기 맞음) / ✕(판정기 틀림) + 메모. 판정기가 맞으면 비워둬도 된다.", ""]
    if agenda:
        out += ["## 통화 전 어젠다", ""] + [f"{n}. {q}" for n, q in enumerate(agenda, 1)] + [""]
    for r in rows:
        i = r["turn"] - 1
        prev = dialog[i - 1][1] if i > 0 and dialog[i - 1][0] == "me" else None
        nxt = dialog[i + 1][1] if i + 1 < len(dialog) else "(통화 끝)"
        cue_lines = [ln.strip() for ln in r["cue"].splitlines() if ln.strip()]
        j = r["judge"]
        out += ["---", "", f"### [{r['turn']}]{' ⚠' if flagged(r) else ''}"]
        if prev:
            out.append(f"> 나: {prev}")
        out += [f"> **고객: {r['customer']}**", "",
                "❓ AI 질문: " + (" / ".join(cue_lines) or "(없음)"), "",
                f"💡 AI 답변: {r['answer']['answer'] if r['answer'] else '—'}", "",
                f"🗣 실제 매니저: {nxt}", "",
                f"🤖 판정기: 질문 **{j['q']}** · 답변 **{j['a']}**"
                + (f" (고객이 물은 것: {j['ask_what']})" if j.get("asked") else "") + f" — {j['reason']}", "",
                "사람 판정: ", ""]
    (outdir / f"{cid}.md").write_text("\n".join(out) + "\n", encoding="utf-8")


async def run_call(client, args, path, sem, outdir):
    cid = path.stem
    bpath = path.with_name(f"{cid}_briefing.txt")
    briefing = bpath.read_text(encoding="utf-8").strip() if bpath.exists() else ""
    dialog = load_dialog(path)
    points = [i for i, (s, _) in enumerate(dialog) if s == "customer"]

    async with sem:
        agenda, agenda_cost = await make_agenda(client, args.model, briefing)

    async def one(i):
        ctx = dialog[:i + 1]
        async with sem:
            (cue, cu), (ans, au) = await asyncio.gather(
                make_cue(client, args.model, ctx, briefing, agenda),
                suggest.answer(client, args.model, ctx, briefing))
        async with sem:
            j, jc = await judge(client, args.judge_model, dialog, i, briefing, cue, ans)
        return {"turn": i + 1, "customer": dialog[i][1], "cue": cue, "answer": ans, "judge": j,
                "cost": cu["cost_usd"] + au["cost_usd"] + jc,
                "cue_ms": cu["latency_ms"], "answer_ms": au["latency_ms"]}

    rows = await asyncio.gather(*(one(i) for i in points))
    total = agenda_cost + sum(r["cost"] for r in rows)
    split = split_of(cid)
    write_call_md(outdir, cid, split, dialog, agenda, rows, total)
    (outdir / f"{cid}.json").write_text(json.dumps(
        {"id": cid, "split": split, "agenda": agenda, "cost": total, "rows": rows},
        ensure_ascii=False, indent=1), encoding="utf-8")
    flags = sum(1 for r in rows if flagged(r))
    print(f"{cid} ({split}): 고객 말 {len(rows)} · ⚠ {flags} · ${total:.2f}")
    return {"id": cid, "split": split, "rows": rows, "cost": total}


def rates(rows):
    qc = Counter(r["judge"]["q"] for r in rows)
    ac = Counter(r["judge"]["a"] for r in rows)
    q_den = qc["same"] + qc["good"] + qc["weak"] + qc["bad"]
    a_den = ac["correct"] + ac["better"] + ac["wrong"] + ac["missed"]
    pct = lambda n, d: f"{n / d * 100:.0f}%" if d else "-"
    return (f"질문 쓸 만함 {pct(qc['same'] + qc['good'], q_den)} (매니저와 같음 {pct(qc['same'], q_den)}, "
            f"weak {qc['weak']}, bad {qc['bad']} / {q_den}) · 고객이 물은 곳 {a_den}: 맞음 {pct(ac['correct'] + ac['better'], a_den)}, "
            f"틀림 {ac['wrong']}, 놓침 {ac['missed']} · 불필요한 답 {ac['extra']}")


def write_summary(outdir, results, args):
    out = [f"# 턴 평가 요약 — {args.name}", "",
           f"모델 {args.model} · 판정기 {args.judge_model} · 비용 ${sum(r['cost'] for r in results):.2f}", ""]
    for split in ("tune", "test"):
        rs = [r for r in results if r["split"] == split]
        if not rs:
            continue
        rows = [row for r in rs for row in r["rows"]]
        out += [f"## {split} ({len(rs)}건, 고객 말 {len(rows)}곳)", "", rates(rows), ""]
        out += [f"- {r['id']}: {rates(r['rows'])}" for r in rs] + [""]
    (outdir / "summary.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n" + "\n".join(out[4:]))


def collect(paths, args):
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.txt")) if p.is_dir() else [p]
    files = [f for f in files if not f.stem.endswith(("_briefing", "_posting"))]
    if args.ids:
        want = set(args.ids.split(","))
        files = [f for f in files if f.stem in want]
    if args.set != "all":
        files = [f for f in files if split_of(f.stem) == args.set]
    return files[:args.limit] if args.limit else files


async def main_async(args):
    files = collect(args.paths, args)
    if args.dry_run:
        n = {"tune": 0, "test": 0}
        for f in files:
            pts = sum(1 for s, _ in load_dialog(f) if s == "customer")
            n[split_of(f.stem)] += pts
            print(f"{f.stem} ({split_of(f.stem)}): 고객 말 {pts}곳")
        print(f"\n{len(files)}건 · tune 고객 말 {n['tune']}곳 · test {n['test']}곳")
        return
    outdir = Path(args.out) / args.name
    outdir.mkdir(parents=True, exist_ok=True)
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(args.concurrency)
    results = await asyncio.gather(*(run_call(client, args, f, sem, outdir) for f in files))
    write_summary(outdir, results, args)
    print(f"\n→ {outdir}/")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("paths", nargs="+", help="변환된 녹취 폴더(sample/calls) 또는 .txt 파일들")
    p.add_argument("--set", choices=("tune", "test", "all"), default="tune")
    p.add_argument("--ids", help="쉼표로 구분한 통화 ID만")
    p.add_argument("--limit", type=int, default=0, help="앞에서 N건만")
    p.add_argument("--name", default=time.strftime("run_%Y%m%d_%H%M"))
    p.add_argument("--model", default="gpt-4.1")
    p.add_argument("--judge-model", default="gpt-4.1")
    p.add_argument("--out", default="sample/review/eval")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--dry-run", action="store_true", help="건수·배정만 보고 API는 안 부른다")
    load_dotenv()
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
