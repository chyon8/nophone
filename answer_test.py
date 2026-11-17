"""제안 답변 테스트 (DESIGN.md 2026-11-17) — 실제 통화 녹취의 고객 말마다 '제안 답변'을 뽑아
실제 매니저 답과 나란히 놓은 검토 문서를 만든다. 판정은 사람이 한다 (지표 없음).

고객 말 하나하나는 그 시점까지의 대화만 보고 따로 판단하므로 병렬로 돌린다.
결과는 실제 고객 내용이라 sample/review/ (gitignore)에만 쓴다.

    uv run answer_test.py sample/golden/156925.txt          # 1건
    uv run answer_test.py sample/golden/1*[0-9].txt         # 여러 건
"""
import argparse
import asyncio
import json
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI

import suggest

# '안 띄운 고객 질문' 목록용 대충 필터 — 놓친 걸 사람이 훑어보라고 보여주는 것뿐
QUESTION_RE = re.compile(r"\?|나요|까요|가요|어떻게")


def load_turns(path):
    speaker_of = {v: k for k, v in suggest.LABELS.items()}
    turns = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        label, sep, text = line.strip().partition(":")
        speaker = speaker_of.get(label.strip())
        if sep and speaker and text.strip():
            turns.append((speaker, text.strip()))
    return turns


async def run_call(client, model, path, sem, outdir):
    path = Path(path)
    bpath = path.with_name(f"{path.stem}_briefing.txt")
    briefing = bpath.read_text(encoding="utf-8").strip() if bpath.exists() else ""
    turns = load_turns(path)
    idx = [i for i, (s, _) in enumerate(turns) if s == "customer"]

    async def one(i):
        async with sem:
            return await suggest.answer(client, model, turns[:i + 1], briefing)

    results = await asyncio.gather(*(one(i) for i in idx))
    total_cost = sum(u["cost_usd"] for _, u in results)
    hits = [(i, d) for i, (d, _) in zip(idx, results) if d]
    lat = [u["latency_ms"] for _, u in results]

    out = [f"# {path.stem} — 제안 답변 검토", "",
           f"고객 말 {len(idx)}개 중 **{len(hits)}개**에 답이 뜸 · 비용 ${total_cost:.2f} · "
           f"답 생성 평균 {sum(lat) / len(lat):.0f}ms", "",
           "각 항목 `판정:` 뒤에 ○(쓸 만함) / △(애매) / ✕(틀림·불필요) + 한 줄 메모", ""]
    for i, d in hits:
        prev = turns[i - 1][1] if i > 0 and turns[i - 1][0] == "me" else None
        nxt = turns[i + 1][1] if i + 1 < len(turns) and turns[i + 1][0] == "me" else "(바로 이어 말 없음)"
        out += ["---", "", f"### [{i + 1}]"]
        if prev:
            out.append(f"> 나: {prev}")
        out += [f"> **고객: {turns[i][1]}**", "",
                f"💡 **제안 답변**: {d['answer']}", "",
                f"실제 매니저: {nxt}", "", "판정: ", ""]

    missed = [i for i, (d, _) in zip(idx, results) if not d and QUESTION_RE.search(turns[i][1])]
    out += ["---", "", "## 안 띄운 고객 질문 (놓친 게 있나 훑어보기용)", ""]
    out += [f"- [{i + 1}] {turns[i][1][:150]}" for i in missed] or ["- 없음"]

    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{path.stem}_answers.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    # 생각 과정(프로젝트·의도·기술)은 화면엔 안 띄우지만 진단용으로 남긴다
    (outdir / f"{path.stem}_answers.json").write_text(json.dumps(
        [{"turn": i + 1, "customer": turns[i][1], **d} for i, d in hits],
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{path.stem}: 고객 말 {len(idx)} · 답 {len(hits)} · ${total_cost:.2f} "
          f"→ {outdir / (path.stem + '_answers.md')}")
    return total_cost


async def main_async(args):
    client = AsyncOpenAI()
    sem = asyncio.Semaphore(args.concurrency)
    costs = await asyncio.gather(*(run_call(client, args.model, p, sem, Path(args.out))
                                   for p in args.transcripts))
    print(f"합계 ${sum(costs):.2f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("transcripts", nargs="+", help="replay 형식 대화록 (`고객:`/`나:`), 옆에 {id}_briefing.txt 있으면 같이 씀")
    p.add_argument("--model", default="gpt-4.1")
    p.add_argument("--out", default="sample/review")
    p.add_argument("--concurrency", type=int, default=8)
    load_dotenv()
    asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
