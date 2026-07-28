"""채점 계층 (SCORING_SPEC.md 구현): 11섹션 confidence는 LLM이 평가하고,
completion·질문 우선도·상담 종료 판별은 코드로 계산한다 (스펙 §4 — 합산을 AI에 맡기지 않음).

섹션 정의·가중치·기준을 바꿀 때는 SCORING_SPEC.md를 먼저 고치고 여기에 반영한다.
"""
import json

# v3.3(2026-07-28): users(타겟 사용자/규모) 제거 — 대부분 통화에서 중요도 낮음(TUNING P-users).
# 그 5%는 같은 '프로젝트 개요' 그룹인 purpose로 이관(0.15→0.20). 합계 1.0 유지.
WEIGHTS = {
    "purpose": 0.20, "core_problem": 0.10, "features": 0.20, "admin": 0.10,
    "platform": 0.10, "integrations": 0.05, "design": 0.05,
    "tech_stack": 0.05, "budget": 0.05, "timeline": 0.05, "deliverables": 0.05,
}

KO = {
    "purpose": "프로젝트 목적/개요", "core_problem": "핵심 문제/현재 운영방식",
    "features": "사용자 핵심 기능", "admin": "관리자 기능",
    "platform": "플랫폼/개발 범위", "integrations": "외부 연동", "design": "디자인 범위",
    "tech_stack": "기술 스택/인프라", "budget": "예산", "timeline": "일정",
    "deliverables": "산출물/자격요건/우대사항",
}

# 스펙 §3의 채점 기준표 압축본. 상세 기준·예시는 SCORING_SPEC.md 원문 참고.
CRITERIA = """- purpose(프로젝트 목적/개요): 0~20 "앱 만들어주세요" 수준 · 51~80 무엇을+왜 만드는지 서술 · 81~100 비즈니스 목표·기대효과 구체적
- core_problem(핵심 문제/현재 운영방식): 21~50 "기존 시스템 없음" 확인 정도 · 51~80 운영방식+불편 서술 · 81~100 구체적 페인포인트+디지털화 이유
- features(사용자 핵심 기능, 최대 가중치): 21~40 추상적 1~2개 · 41~60 3~5개 나열 · 61~80 모듈별 구분+사용자 흐름 · 81~100 모듈별 입출력·동작까지 구체적
- admin(관리자 기능, 고객이 가장 많이 빠뜨림): 0 언급 없음 · 1~40 "관리자 페이지 필요" 정도 · 71~100 권한·대시보드·데이터 관리 구체적
- platform(플랫폼/개발 범위): 0 웹/앱 구분 없음 · 41~70 플랫폼 명시, 신규/고도화 불명확 · 71~100 플랫폼+개발범위+확장계획
- integrations(외부 연동): 1~50 필요하다고만 · 51~100 구체적 서비스명 명시 또는 "연동 없음" 확인됨
- design(디자인 범위): 1~50 "디자인도 해주세요" 정도 · 51~100 시안 유무/기존 활용/개발사 일임/참고 사이트 구체적
- tech_stack(기술 스택/인프라): 1~50 매우 추상적 · 51~100 구체적 스택 명시 또는 "제안 요청" 명시
- budget(예산): 1~50 "합리적인 가격" 등 모호 · 51~100 구체적 금액 또는 "견적 후 협의" 명시
- timeline(일정): 1~50 "빨리" 등 모호 · 51~100 착수일/납품일 또는 "착수 후 N개월" 구체적
- deliverables(산출물/자격요건/우대사항): 1~50 "소스코드 주세요" 정도 · 51~100 산출물 목록+지원 자격+우대사항 명시"""

SCORER_SYSTEM = f"""위시켓 프로젝트 검수 상담을 분석해, 공고문 작성에 필요한 11개 섹션 각각의
정보 확보 수준(confidence 0~100)과 처리 상태(status)를 평가한다.

원칙 (목표 = 완벽한 명세가 아니라 '개발사가 견적 낼 수 있는 공고 등록 가능선'):
- 공고문을 바로 쓸 수 있을 만큼 구체적일수록 confidence가 높다.
- 프로젝트 유형상 자명한 통상 기능·관례(일반 CRUD 입출력, 표준 로그인/회원가입, 리스트·검색·필터,
  통상적 관리자 조회·관리)는 고객이 일일이 말하지 않아도 확보로 본다. 관례적 세부까지 캐물어 깎지 않는다.
- 단, 프로젝트 고유의 사실(예산·일정·규모, 고유/차별 기능, 특정 외부 연동·브랜드, 비표준 요구사항)은
  언급돼야 확보다. 이건 추측하지 않는다 — 없으면 미확인/미정.

브리핑 vs 대화록 우선순위: [통화 전 초기 등록 내용](브리핑)은 참고용 초기 정보일 뿐이다.
대화록과 충돌하면 무조건 대화록을 진실로 삼는다 — 브리핑에만 있고 대화에서 다르게 말했거나
부정된 내용은 채점 근거로 쓰지 않는다.

status는 이 섹션을 통화에서 어떻게 처리했는지다 (대화록 근거로만 판정):
- "확보": 고객이 관련 내용을 말해 정보를 얻음. confidence는 얼마나 구체적인지.
- "미정": 물어봤으나 고객이 아직 결정 못 했거나, 개발사에 위임했거나, **모른다고 답한 경우**
  ("아직 안 정했다", "제안해달라", "제가 이쪽은 잘 몰라서" 등). 비전문 고객의 "모름"은 위임과 같다.
  같은 축을 여러 번 물었는데도 실질적인 답이 안 나오면 그것도 미정으로 닫는다 — 계속 캐묻지 않게.
- "불필요": 이 프로젝트엔 해당 없음. 고객이 명시했거나("그건 필요 없다"), **또는 프로젝트 유형상 명백히 해당 없는 경우**.
  예: 순수 하드웨어/펌웨어 시제품, 백엔드 운영이 없는 물리 디바이스, 단순 API 연동처럼 운영 주체가 없는 프로젝트의 "관리자 기능"·"외부 연동"·"플랫폼";
  개발사가 알아서 정할 뿐 고객 관여가 없는 항목 등. 이런 섹션을 억지로 캐물어 완성도를 깎지 말고 불필요로 판정한다.
  **단, 있을 법하면(애매하면) 불필요로 단정하지 말고 미확인으로 둔다** — 오탐이 진짜 필요한 걸 숨기지 않게.
- "미확인": 통화에서 아직 다루지 않았고, 유형상 해당 없음도 아님(다뤄야 하는데 안 다룸). 근거가 없으면 이 값.

섹션별 confidence 기준:
{CRITERIA}

브리핑 불일치 판정 (briefing_conflict):
- "none": 브리핑이 없거나 대화와 상충하지 않음.
- "minor": 세부 값이 다름(예산·일정·규모 등 일부 수치·항목 차이). 대화 우선 원칙으로 흡수되므로 신호 불필요.
- "major": 브리핑이 통화와 근본적으로 다른 프로젝트/범위로 보임(다른 도메인·다른 제품). note에 무엇이 어떻게 다른지 한 줄.
- 브리핑이 없으면 반드시 "none".

JSON만 출력한다. briefing_conflict 1개 + 11개 섹션 전부 포함, 각 섹션에 status·confidence·evidence:
{{"briefing_conflict": {{"level": "none", "note": ""}}, "sections": {{"purpose": {{"status": "확보", "confidence": 0, "evidence": "..."}}, ...}}}}
evidence는 다음 질문 생성의 근거가 되므로 근거 발화를 짧고 구체적으로 적는다
(금액·수치·고유명사 포함). 미확인이면 "미언급"."""


STATUSES = ("확보", "미정", "불필요", "미확인")
EFFECTIVE = {"미정": 70, "불필요": 100, "미확인": 0}  # 확보는 confidence 사용. 스펙 §2.5·§4


def effective_score(sec) -> int:
    """status를 반영한 completion용 유효 점수. 스펙 §4."""
    if sec.get("status") == "확보":
        return sec.get("confidence", 0)
    return EFFECTIVE.get(sec.get("status", "미확인"), 0)


def completion(sections) -> int:
    """overall_completion = Σ (effective_score × weight). 스펙 §4 (v3: status 반영)."""
    return round(sum(effective_score(sections.get(k, {})) * w for k, w in WEIGHTS.items()))


def can_close(sections) -> bool:
    """상담 종료 = completion ≥ 70 AND 핵심 3섹션(features/purpose/platform)이 실제 '확보'+conf≥50.
    스펙 §5 (v3: 핵심 3섹션은 유효점수 미정=70으로 못 넘고 반드시 확보여야 한다)."""
    core_ok = all(sections.get(k, {}).get("status") == "확보"
                  and sections.get(k, {}).get("confidence", 0) >= 50
                  for k in ("features", "purpose", "platform"))
    return completion(sections) >= 70 and core_ok


def grade(comp: int) -> str:
    if comp < 40:
        return "🔴 초기"
    if comp < 70:
        return "🟡 진행중"
    if comp < 85:
        return "🟢 등록가능"
    return "🔵 완성"


def priorities(sections):
    """[(섹션ID, 우선도, confidence)] 내림차순. 우선도 = 가중치 × (100 - confidence). 스펙 §6.
    v3: status로 선필터 — 미정·불필요는 재질문 안 함(제외), 미확인은 conf 0, 확보는 conf≥80이면 제외."""
    rows = []
    for k, w in WEIGHTS.items():
        sec = sections.get(k, {})
        status = sec.get("status", "미확인")
        if status in ("미정", "불필요"):
            continue                       # 이미 다룸 — 반복 질문 금지
        conf = 0 if status == "미확인" else sec.get("confidence", 0)
        if status == "확보" and conf >= 80:
            continue
        rows.append((k, w * (100 - conf), conf))
    return sorted(rows, key=lambda r: -r[1])


async def score(client, model, briefing, transcript_lines):
    """브리핑+대화록 전체를 재채점해 (sections, conflict, resp)를 돌려준다.
    파싱 실패 시 (None, None, resp) — resp는 비용 기록용(usage). 입력 없으면 (None, None, None).
    sections = {섹션ID: {status, confidence, evidence}}, conflict = {level, note} (브리핑 불일치)."""
    parts = []
    if briefing:
        parts.append(f"[통화 전 초기 등록 내용]\n{briefing}")
    if transcript_lines:
        parts.append("[통화 대화록]\n" + "\n".join(transcript_lines))
    if not parts:
        return None, None, None
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SCORER_SYSTEM},
                  {"role": "user", "content": "\n\n".join(parts)}],
        response_format={"type": "json_object"},
        max_completion_tokens=1500,
    )
    try:
        data = json.loads(resp.choices[0].message.content)
        secs = data["sections"]
        out = {}
        for k in WEIGHTS:
            s = secs.get(k, {}) or {}
            status = s.get("status", "미확인")
            if status not in STATUSES:
                status = "미확인"
            out[k] = {"status": status,
                      "confidence": max(0, min(100, int(s.get("confidence", 0)))),
                      "evidence": str(s.get("evidence", "미언급"))}
        bc = data.get("briefing_conflict") or {}
        level = bc.get("level", "none")
        if level not in ("none", "minor", "major") or not briefing:
            level = "none"
        conflict = {"level": level, "note": str(bc.get("note", ""))}
        return out, conflict, resp
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None, None, resp
