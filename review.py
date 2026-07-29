"""review.py — 통화 1건을 턴 순서로 훑어보는 리뷰 도구 (조회 전용).

테스트가 끝난 뒤 "이 발화에 이 큐가 떴다"를 나란히 놓고 보기 위한 것.
어디가 어색했는지 짚어서 판단 레이어 설계의 재료로 쓴다 (HANDOFF.md 2026-07-28).

DB를 읽기만 한다. 기록은 통화 중 server.py가 자동으로 남긴다.

    uv run review.py                 통화 목록
    uv run review.py --last          마지막 통화 상세
    uv run review.py 9eadc156        특정 통화 상세 (id 앞자리만 써도 됨)
"""
import argparse
import sys
from datetime import datetime

import db

LABELS = {"customer": "고객", "me": "나"}
W = 62


def _hms(iso):
    """ISO 문자열 → HH:MM:SS."""
    return iso[11:19] if iso and len(iso) >= 19 else "--:--:--"


def _duration(started, ended):
    if not (started and ended):
        return "진행 중"
    sec = int((datetime.fromisoformat(ended) - datetime.fromisoformat(started)).total_seconds())
    return f"{sec // 60}분 {sec % 60}초"


def _stats(conn, call_id):
    """통화 1건의 발화 수·큐 수·비용·큐 생성 평균 지연."""
    utts = db.get_utterances(conn, call_id)
    sugs = db.get_suggestions(conn, call_id)
    events = db.get_usage_events(conn, call_id)
    cues = [s for s in sugs if s["prompt_id"] == db.BUILTIN_REPLY_ID]
    lat = [e["latency_ms"] for e in events if e["kind"] == "suggest" and e["latency_ms"]]
    return {
        "utts": utts,
        "cues": cues,
        "agenda": next((s for s in sugs if s["prompt_id"] == db.BUILTIN_AGENDA_ID), None),
        "cost": sum(e["cost_usd"] for e in events),
        "avg_ms": sum(lat) / len(lat) if lat else None,
    }


def list_calls(conn, limit):
    calls = db.get_calls(conn)[:limit]
    if not calls:
        print("통화 기록이 없습니다. `uv run server.py`로 통화를 한 번 해보세요.")
        return
    print(f"\n통화 기록 (최근 {len(calls)}건)\n")
    print("  시작              발화   큐      비용   id")  # 한글은 2칸이라 폭을 눈으로 맞춤
    print(f"  {'─' * (W - 2)}")
    for c in calls:
        s = _stats(conn, c["id"])
        started = c["started_at"][:16].replace("T", " ")
        print(f"  {started:<17}{len(s['utts']):>5}{len(s['cues']):>5}"
              f"{'$' + format(s['cost'], '.4f'):>10}   {c['id'][:8]}")
    print(f"\n상세: uv run review.py <id>  ·  마지막 통화: uv run review.py --last\n")


def show_call(conn, call):
    s = _stats(conn, call["id"])
    print(f"\n{'═' * W}")
    print(f"{call['started_at'].replace('T', ' ')}  ({_duration(call['started_at'], call['ended_at'])})")
    line = f"발화 {len(s['utts'])} · 큐 {len(s['cues'])} · 비용 ${s['cost']:.4f}"
    if s["avg_ms"]:
        line += f" · 큐 생성 평균 {s['avg_ms']:.0f}ms(완료까지)"
    print(line)
    print(f"id {call['id']}")
    print(f"{'═' * W}")

    if s["agenda"]:
        print("\n📌 통화 전 어젠다 (질문 지도)")
        for i, q in enumerate(s["agenda"]["content"].splitlines(), 1):
            print(f"   {i}. {q}")
    elif s["utts"]:
        print("\n📌 어젠다 없음 (브리핑 없이 시작 = 콜드스타트)")

    if not s["utts"]:
        print("\n발화가 없습니다.\n")
        return

    # 발화와 큐를 시각순으로 병합한다. 같은 초면 발화를 먼저 — 큐는 발화 뒤에 나오므로.
    rows = ([(u["created_at"], 0, u) for u in s["utts"]]
            + [(c["created_at"], 1, c) for c in s["cues"]])
    rows.sort(key=lambda r: (r[0], r[1]))

    print(f"\n{'─' * W}")
    turn = 0
    for created_at, is_cue, row in rows:
        if is_cue:
            print(f"\n     💬 {_hms(created_at)}")
            for ln in row["content"].splitlines():
                if ln.strip():
                    print(f"        {ln.strip()}")
        else:
            turn += 1
            print(f"\n[{turn:>2}] {_hms(created_at)}  {LABELS.get(row['speaker'], row['speaker'])}")
            print(f"     {row['text']}")

    print(f"\n{'─' * W}")
    if call["summary"]:
        print(f"\n📋 공고 draft\n{'═' * W}\n{call['summary']}")
    else:
        print("\n📋 공고 draft 없음 (통화를 [통화 종료]로 끝내야 생성됩니다)")
    print()


def main():
    p = argparse.ArgumentParser(description="통화 기록을 턴 순서로 리뷰 (조회 전용)")
    p.add_argument("call_id", nargs="?", help="통화 id (앞자리만 써도 됨). 없으면 목록")
    p.add_argument("--last", action="store_true", help="마지막 통화 상세")
    p.add_argument("--limit", type=int, default=20, help="목록에 보여줄 통화 수 (기본 20)")
    args = p.parse_args()

    conn = db.connect()
    calls = db.get_calls(conn)

    if args.last:
        if not calls:
            print("통화 기록이 없습니다.")
            return
        show_call(conn, calls[0])
    elif args.call_id:
        matched = [c for c in calls if c["id"].startswith(args.call_id)]
        if not matched:
            print(f"'{args.call_id}'로 시작하는 통화가 없습니다. `uv run review.py`로 목록을 보세요.")
            sys.exit(1)
        if len(matched) > 1:
            print(f"'{args.call_id}'에 해당하는 통화가 {len(matched)}건입니다. 앞자리를 더 주세요:")
            for c in matched:
                print(f"  {c['id']}  {c['started_at']}")
            sys.exit(1)
        show_call(conn, matched[0])
    else:
        list_calls(conn, args.limit)


if __name__ == "__main__":
    main()
