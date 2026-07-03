"""DB 모듈: DESIGN.md 확정 스키마(테이블 5개)의 생성·기본 프롬프트 시드·CRUD.

- SQLite, UUID PK, Postgres 호환 타입만 사용 (팀 확장 시 이전 대비 — DESIGN.md)
- FK 정책: 고객 삭제 → 통화는 남기고 연결만 해제 / 통화 삭제 → 발화·제안 연쇄 삭제

단독 실행:
    uv run db.py             # data/nophone.db 생성 + 기본 프롬프트 시드
    uv run db.py --selftest  # 메모리 DB로 왕복 검증 (실 DB는 건드리지 않음)
"""
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = "data/nophone.db"
SCHEMA_VERSION = 1
BUILTIN_REPLY_ID = "builtin-reply"  # 자동 멘트 제안용 내장 프롬프트 (버튼으론 안 나옴: sort_order=0)

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    company TEXT,
    phone TEXT,
    memo TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calls (
    id TEXT PRIMARY KEY,
    customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
    agent TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    title TEXT,
    summary TEXT,
    audio_path TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS utterances (
    id TEXT PRIMARY KEY,
    call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    speaker TEXT NOT NULL CHECK (speaker IN ('customer', 'me')),
    text TEXT NOT NULL,
    ms INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    template TEXT NOT NULL,
    sort_order INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestions (
    id TEXT PRIMARY KEY,
    call_id TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    prompt_id TEXT REFERENCES prompts(id),
    prompt_text TEXT NOT NULL,
    content TEXT NOT NULL,
    model TEXT,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_calls_customer ON calls(customer_id);
CREATE INDEX IF NOT EXISTS idx_calls_started ON calls(started_at);
CREATE INDEX IF NOT EXISTS idx_utterances_call ON utterances(call_id);
CREATE INDEX IF NOT EXISTS idx_suggestions_call ON suggestions(call_id);
"""

SEED_PROMPTS = [
    (BUILTIN_REPLY_ID, "다음 멘트 제안", 0,
     "너는 IT 프로젝트 수주 상담을 돕는 코파일럿이다. 지금까지의 통화 내용을 읽고, "
     "상담원('나')이 바로 이어서 하면 좋을 말을 한두 문장의 실제 대사로 제안하라. "
     "존댓말 통화체로, 설명 없이 대사만 출력하라."),
    (None, "견적 초안", 1,
     "지금까지의 통화에서 파악된 요구사항을 바탕으로 견적 초안을 작성하라. "
     "구성: 1) 파악된 범위 요약 2) 단계별 항목과 예상 공수 3) 예상 금액 범위 "
     "4) 전제조건/제외사항. 통화에서 언급되지 않은 정보는 추측하지 말고 '확인 필요'로 표시하라."),
    (None, "요구사항 정리", 2,
     "통화에서 언급된 요구사항을 표로 정리하라. 컬럼: 항목 / 내용 / 우선순위 / 미확정 여부. "
     "고객이 직접 말한 것과 상담원이 제안한 것을 구분하라."),
    (None, "절차 설명", 3,
     "일반적인 IT 프로젝트 진행 절차(상담 → 요구사항 정리 → 견적 → 계약 → 설계 → 개발 → "
     "검수 → 배포 → 유지보수)를 지금 고객 상황에 맞춰 안내하는 멘트를 작성하라. "
     "지금 어느 단계인지 짚어주고 다음 단계를 안내하라."),
    (None, "통화 요약", 4,
     "이 통화를 요약하라. 구성: 1) 한 줄 제목 2) 핵심 내용 3~5개 3) 고객 요구/조건 "
     "4) 우리가 한 약속 5) 다음 액션 아이템."),
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id() -> str:
    return str(uuid.uuid4())


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    """DB 연결 + 스키마 생성 + 시드. 모든 사용처는 이 함수로만 연결한다."""
    if path != ":memory:":
        Path(path).parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    if conn.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 0:
        for pid, name, order, template in SEED_PROMPTS:
            conn.execute(
                "INSERT INTO prompts (id, name, template, sort_order, created_at) VALUES (?,?,?,?,?)",
                (pid or _id(), name, template, order, _now()))
    conn.commit()
    return conn


# --- customers ---

def create_customer(conn, name, company=None, phone=None, memo=None) -> str:
    cid = _id()
    conn.execute("INSERT INTO customers (id, name, company, phone, memo, created_at) VALUES (?,?,?,?,?,?)",
                 (cid, name, company, phone, memo, _now()))
    conn.commit()
    return cid


def get_customers(conn):
    return conn.execute("SELECT * FROM customers ORDER BY created_at DESC").fetchall()


def delete_customer(conn, customer_id):
    conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    conn.commit()


# --- calls ---

def create_call(conn, agent=None) -> str:
    call_id = _id()
    t = _now()
    conn.execute("INSERT INTO calls (id, agent, started_at, created_at) VALUES (?,?,?,?)",
                 (call_id, agent, t, t))
    conn.commit()
    return call_id


def update_call(conn, call_id, **fields):
    """ended_at / title / summary / audio_path / customer_id 갱신용."""
    allowed = {"ended_at", "title", "summary", "audio_path", "customer_id"}
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    sets = ", ".join(f"{k} = ?" for k in keys)
    conn.execute(f"UPDATE calls SET {sets} WHERE id = ?", [fields[k] for k in keys] + [call_id])
    conn.commit()


def get_calls(conn):
    return conn.execute("SELECT * FROM calls ORDER BY started_at DESC").fetchall()


def get_call(conn, call_id):
    return conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()


def delete_call(conn, call_id):
    conn.execute("DELETE FROM calls WHERE id = ?", (call_id,))
    conn.commit()


# --- utterances ---

def add_utterance(conn, call_id, speaker, text, ms) -> str:
    uid = _id()
    conn.execute("INSERT INTO utterances (id, call_id, speaker, text, ms, created_at) VALUES (?,?,?,?,?,?)",
                 (uid, call_id, speaker, text, ms, _now()))
    conn.commit()
    return uid


def get_utterances(conn, call_id):
    return conn.execute("SELECT * FROM utterances WHERE call_id = ? ORDER BY ms", (call_id,)).fetchall()


# --- prompts ---

def get_prompts(conn, active_only=True):
    q = "SELECT * FROM prompts"
    if active_only:
        q += " WHERE active = 1"
    return conn.execute(q + " ORDER BY sort_order").fetchall()


# --- suggestions ---

def add_suggestion(conn, call_id, prompt_id, prompt_text, content, model=None) -> str:
    sid = _id()
    conn.execute(
        "INSERT INTO suggestions (id, call_id, prompt_id, prompt_text, content, model, created_at) VALUES (?,?,?,?,?,?,?)",
        (sid, call_id, prompt_id, prompt_text, content, model, _now()))
    conn.commit()
    return sid


def mark_suggestion_used(conn, suggestion_id):
    conn.execute("UPDATE suggestions SET used = 1 WHERE id = ?", (suggestion_id,))
    conn.commit()


def get_suggestions(conn, call_id):
    return conn.execute("SELECT * FROM suggestions WHERE call_id = ? ORDER BY created_at", (call_id,)).fetchall()


# --- selftest ---

def selftest():
    conn = connect(":memory:")
    ok = 0

    def check(name, cond):
        nonlocal ok
        assert cond, f"FAIL: {name}"
        ok += 1
        print(f"  PASS {name}")

    check("테이블 5개 생성", conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN "
        "('customers','calls','utterances','prompts','suggestions')").fetchone()[0] == 5)
    check("스키마 버전 = 1", conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION)
    check("기본 프롬프트 5종 시드", len(get_prompts(conn)) == 5)
    check("내장 멘트 제안 프롬프트 존재",
          conn.execute("SELECT id FROM prompts WHERE id = ?", (BUILTIN_REPLY_ID,)).fetchone() is not None)

    cid = create_customer(conn, "홍길동", company="테스트상사", phone="01012345678")
    call_id = create_call(conn, agent="나")
    update_call(conn, call_id, customer_id=cid, title="테스트 통화")
    add_utterance(conn, call_id, "customer", "예산이 3천만원입니다", 1000)
    add_utterance(conn, call_id, "me", "네, 확인했습니다", 4000)
    sid = add_suggestion(conn, call_id, BUILTIN_REPLY_ID, "프롬프트 원문", "제안 내용", model="gpt-5-mini")

    check("통화-고객 연결", get_call(conn, call_id)["customer_id"] == cid)
    check("발화 2건 저장·ms 정렬", [u["ms"] for u in get_utterances(conn, call_id)] == [1000, 4000])
    check("잘못된 화자 거부", not _insert_bad_speaker(conn, call_id))
    check("제안 저장", get_suggestions(conn, call_id)[0]["content"] == "제안 내용")

    mark_suggestion_used(conn, sid)
    check("used 플래그", get_suggestions(conn, call_id)[0]["used"] == 1)

    delete_customer(conn, cid)
    check("고객 삭제 → 통화는 남고 연결만 해제",
          get_call(conn, call_id) is not None and get_call(conn, call_id)["customer_id"] is None)

    delete_call(conn, call_id)
    check("통화 삭제 → 발화·제안 연쇄 삭제",
          len(get_utterances(conn, call_id)) == 0 and len(get_suggestions(conn, call_id)) == 0)

    print(f"셀프테스트 통과: {ok}/{ok}")


def _insert_bad_speaker(conn, call_id) -> bool:
    try:
        conn.execute("INSERT INTO utterances (id, call_id, speaker, text, ms, created_at) VALUES (?,?,?,?,?,?)",
                     (_id(), call_id, "invalid", "x", 0, _now()))
        return True
    except sqlite3.IntegrityError:
        return False


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    connect()
    print(f"DB 준비 완료: {DB_PATH} (프롬프트 {len(get_prompts(connect()))}종)")
