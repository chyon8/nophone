"""LLM 호출 비용 계산 — usage(토큰) → USD.

목적: 프로덕트 편입 시 '월 예상 비용'을 뽑기 위한 원자료. 모든 LLM 호출을 한 건씩
usage_events(db.py)에 남긴다. 조립·집계는 나중에 SQL로.

⚠ 단가(PRICES)는 수시로 바뀐다. 최신값 확인 후 갱신할 것.
   (아래는 OpenAI 2025 공개가 기준 — 사용자 확인 대기, DESIGN.md 참고.)
"""

# $ per 1,000,000 tokens
PRICES = {
    "gpt-4.1":                 {"in": 2.00, "cached_in": 0.50, "out": 8.00},
    "gpt-4.1-mini":            {"in": 0.40, "cached_in": 0.10, "out": 1.60},
    "gpt-4o-transcribe":       {"in": 2.50, "cached_in": 2.50, "out": 10.00},  # STT(참고)
    "text-embedding-3-large":  {"in": 0.13, "cached_in": 0.13, "out": 0.00},
}


def cost_of(model, prompt_tokens, completion_tokens, cached_tokens=0) -> float:
    """토큰 수 → USD. 단가 미등록 모델은 0 (단, 토큰은 그대로 저장돼 나중에 재계산 가능)."""
    p = PRICES.get(model)
    if not p:
        return 0.0
    billable_in = max(0, prompt_tokens - cached_tokens)
    usd = (billable_in * p["in"] + cached_tokens * p["cached_in"]
           + completion_tokens * p["out"]) / 1_000_000
    return round(usd, 6)


def usage_fields(resp) -> dict:
    """OpenAI 응답/스트림청크의 .usage → {prompt,completion,cached}_tokens. 없으면 0."""
    u = getattr(resp, "usage", None)
    if not u:
        return {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
    cached = 0
    details = getattr(u, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    return {
        "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
        "cached_tokens": cached,
    }


def event(kind, model, resp, latency_ms=None) -> dict:
    """호출 1건의 usage_events 페이로드(비용 포함). db.add_usage_event(**event)로 저장.

    kind: agenda|suggest|score|posting|customer_sim|embedding
    resp: .usage를 가진 응답(비스트림) 또는 usage 청크(스트림). None이면 0으로 기록.
    """
    u = usage_fields(resp)
    return {
        "kind": kind,
        "model": model,
        "prompt_tokens": u["prompt_tokens"],
        "completion_tokens": u["completion_tokens"],
        "cached_tokens": u["cached_tokens"],
        "cost_usd": cost_of(model, u["prompt_tokens"], u["completion_tokens"], u["cached_tokens"]),
        "latency_ms": round(latency_ms) if latency_ms is not None else None,
    }
