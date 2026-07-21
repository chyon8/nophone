"""채점 계층 (SCORING_SPEC.md 구현): 12섹션 confidence는 LLM이 평가하고,
completion·질문 우선도·상담 종료 판별은 코드로 계산한다 (스펙 §4 — 합산을 AI에 맡기지 않음).

섹션 정의·가중치·기준을 바꿀 때는 SCORING_SPEC.md를 먼저 고치고 여기에 반영한다.
"""
import json

WEIGHTS = {
    "purpose": 0.15, "core_problem": 0.10, "features": 0.20, "admin": 0.10,
    "users": 0.05, "platform": 0.10, "integrations": 0.05, "design": 0.05,
    "tech_stack": 0.05, "budget": 0.05, "timeline": 0.05, "deliverables": 0.05,
}

KO = {
    "purpose": "프로젝트 목적/개요", "core_problem": "핵심 문제/현재 운영방식",
    "features": "사용자 핵심 기능", "admin": "관리자 기능", "users": "타겟 사용자/규모",
    "platform": "플랫폼/개발 범위", "integrations": "외부 연동", "design": "디자인 범위",
    "tech_stack": "기술 스택/인프라", "budget": "예산", "timeline": "일정",
    "deliverables": "산출물/자격요건/우대사항",
}

# 스펙 §3의 채점 기준표 압축본. 상세 기준·예시는 SCORING_SPEC.md 원문 참고.
CRITERIA = """- purpose(프로젝트 목적/개요): 0~20 "앱 만들어주세요" 수준 · 51~80 무엇을+왜 만드는지 서술 · 81~100 비즈니스 목표·기대효과 구체적
- core_problem(핵심 문제/현재 운영방식): 21~50 "기존 시스템 없음" 확인 정도 · 51~80 운영방식+불편 서술 · 81~100 구체적 페인포인트+디지털화 이유
- features(사용자 핵심 기능, 최대 가중치): 21~40 추상적 1~2개 · 41~60 3~5개 나열 · 61~80 모듈별 구분+사용자 흐름 · 81~100 모듈별 입출력·동작까지 구체적
- admin(관리자 기능, 고객이 가장 많이 빠뜨림): 0 언급 없음 · 1~40 "관리자 페이지 필요" 정도 · 71~100 권한·대시보드·데이터 관리 구체적
- users(타겟 사용자/규모): 31~70 사용자/관리자 구분 정도 · 71~100 유형+예상 규모+연령대·특성
- platform(플랫폼/개발 범위): 0 웹/앱 구분 없음 · 41~70 플랫폼 명시, 신규/고도화 불명확 · 71~100 플랫폼+개발범위+확장계획
- integrations(외부 연동): 1~50 필요하다고만 · 51~100 구체적 서비스명 명시 또는 "연동 없음" 확인됨
- design(디자인 범위): 1~50 "디자인도 해주세요" 정도 · 51~100 시안 유무/기존 활용/개발사 일임/참고 사이트 구체적
- tech_stack(기술 스택/인프라): 1~50 매우 추상적 · 51~100 구체적 스택 명시 또는 "제안 요청" 명시
- budget(예산): 1~50 "합리적인 가격" 등 모호 · 51~100 구체적 금액 또는 "견적 후 협의" 명시
- timeline(일정): 1~50 "빨리" 등 모호 · 51~100 착수일/납품일 또는 "착수 후 N개월" 구체적
- deliverables(산출물/자격요건/우대사항): 1~50 "소스코드 주세요" 정도 · 51~100 산출물 목록+지원 자격+우대사항 명시"""

SCORER_SYSTEM = f"""위시켓 프로젝트 검수 상담을 분석해, 공고문 작성에 필요한 12개 섹션의
정보 확보 수준(confidence 0~100)을 평가한다.

원칙:
- 공고문을 바로 쓸 수 있을 만큼 구체적일수록 높다.
- "필요 없음/없음"이 명시적으로 확인된 것도 높은 점수다. 핵심은 확인 여부다.
- 대화에 없는 내용을 추측해서 점수를 올리지 않는다.

섹션별 기준:
{CRITERIA}

JSON만 출력한다. 12개 섹션 전부 포함:
{{"sections": {{"purpose": {{"confidence": 0, "evidence": "..."}}, ...}}}}
evidence는 다음 질문 생성의 근거가 되므로, 확보된 사실을 짧고 구체적으로 적는다
(금액·수치·고유명사 포함). 확보된 게 없으면 "미언급"."""


def completion(sections) -> int:
    """overall_completion = Σ (confidence × weight). 스펙 §4."""
    return round(sum(sections.get(k, {}).get("confidence", 0) * w for k, w in WEIGHTS.items()))


def can_close(sections) -> bool:
    """상담 종료 = completion ≥ 70 AND 핵심 3섹션(features/purpose/platform) ≥ 50. 스펙 §5."""
    core_ok = all(sections.get(k, {}).get("confidence", 0) >= 50
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
    """[(섹션ID, 우선도, confidence)] 내림차순. 우선도 = 가중치 × (100 - confidence),
    confidence ≥ 80은 질문하지 않음. 스펙 §6."""
    rows = []
    for k, w in WEIGHTS.items():
        conf = sections.get(k, {}).get("confidence", 0)
        if conf >= 80:
            continue
        rows.append((k, w * (100 - conf), conf))
    return sorted(rows, key=lambda r: -r[1])


async def score(client, model, briefing, transcript_lines):
    """브리핑+대화록 전체를 재채점해 {섹션ID: {confidence, evidence}}를 돌려준다. 실패 시 None."""
    parts = []
    if briefing:
        parts.append(f"[통화 전 초기 등록 내용]\n{briefing}")
    if transcript_lines:
        parts.append("[통화 대화록]\n" + "\n".join(transcript_lines))
    if not parts:
        return None
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SCORER_SYSTEM},
                  {"role": "user", "content": "\n\n".join(parts)}],
        response_format={"type": "json_object"},
        max_completion_tokens=1500,
    )
    try:
        secs = json.loads(resp.choices[0].message.content)["sections"]
        return {k: {"confidence": max(0, min(100, int(secs.get(k, {}).get("confidence", 0)))),
                    "evidence": str(secs.get(k, {}).get("evidence", "미언급"))}
                for k in WEIGHTS}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
