"""공고 draft 생성 (SCORING_SPEC §1 공고 양식) — 상담의 최종 산출물.

브리핑 + 대화록 + 12섹션 채점을 근거로, 개발사가 추가 미팅 없이 견적 낼 수 있는
수준의 마크다운 공고문을 만든다. 종료 조건(can_close) 충족 시가 정식이지만,
미충족 상태에서도 "지금까지의 draft"로 생성할 수 있다(부족분은 협의/미정 표기).
"""
import scoring

DRAFT_SYSTEM = """당신은 위시켓 검수매니저다. 방금 끝난 프로젝트 상담을 근거로,
개발사가 추가 미팅 없이 견적을 낼 수 있는 수준의 **공고문(마크다운)**을 작성한다.

공고 양식 — 아래 제목·순서 그대로 사용한다:
## 프로젝트 개요
## 프로젝트 배경 및 목표
## 과업 범위
### 수행 범위
### 상세 기능 요구사항
### 관리자 기능
## 기술 스택
## 주요 일정
## 예산
## 지원 자격 및 우대 사항
## 산출물

작성 규칙:
- 대화록·브리핑에서 확인된 사실만 쓴다. 프로젝트 고유 사실(예산·일정·규모·고유 기능·특정 연동)을 지어내지 않는다.
- 브리핑은 통화 전 참고용 초기 정보일 뿐이다. 대화와 충돌하면 무조건 대화를 따른다 — 브리핑에만 있고 대화에서 다르게 말한 내용은 쓰지 않는다.
- **언급되지 않은 날짜(연·월)·숫자·고유명사를 지어내지 않는다.** 연도가 대화에 없으면 연도를 쓰지 말고, 언급된 표현("11~12월 내" 등) 그대로만 쓴다.
- 고객이 미정이거나 개발사에 위임한 항목은 "협의 후 결정" 또는 "개발사 제안"으로 명시한다.
- 프로젝트 유형상 자명한 통상 기능(일반 CRUD, 표준 로그인/회원가입, 리스트·검색 등)은 자연스럽게 포함해도 된다.
- "해당 없음"이 확인된 항목은 생략하거나 "해당 없음"으로 적는다.
- 간결한 개조식. 개발사가 읽고 바로 범위를 파악할 수 있게. 군더더기·인사말 없이 공고 본문만 출력한다."""


async def generate(client, model, briefing, transcript_lines, sections):
    """공고 draft (마크다운, resp)를 반환한다. resp는 비용 기록용(usage). 입력 없으면 ("", None)."""
    parts = []
    if briefing:
        parts.append(f"[사전 브리핑]\n{briefing}")
    if sections:
        status_lines = [f"- {scoring.KO[k]} [{v.get('status', '?')}/{v.get('confidence', 0)}]: {v.get('evidence', '')}"
                        for k, v in sections.items()]
        parts.append("[섹션별 확보 현황 (status/confidence)]\n" + "\n".join(status_lines))
    if transcript_lines:
        parts.append("[통화 대화록]\n" + "\n".join(transcript_lines))
    if not parts:
        return "", None
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": DRAFT_SYSTEM},
                  {"role": "user", "content": "\n\n".join(parts)}],
        max_completion_tokens=2000,
    )
    return (resp.choices[0].message.content or "").strip(), resp
