# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

# 프로젝트: AI 통화 코파일럿 (nophone)

목표·진짜 문제·확정된 스키마·UI/UX·스택·하드웨어는 전부 **[DESIGN.md](DESIGN.md)**에 있음. 설계 변경이 필요하면 코드보다 DESIGN.md를 먼저 갱신하고 컨펌받는다 (룰 9번).

개발 순서·청크 정의·진행 상태는 **[PLAN.md](PLAN.md)**를 따른다. 청크 하나 끝날 때마다 PLAN.md의 상태 표기(⏳→✅)를 갱신한다. 시각 디자인은 **[STYLE.md](STYLE.md)** 무조건 준수 (룰 10번).

## 개발 룰

1. **STT 모듈은 교체 가능하게 분리** — 전화 협대역 음질로 정확도가 부족하면 다른 엔진으로 갈아끼운다.
2. **테스트는 녹음 파일로** — 캡처 모듈은 `--source <file>` 모드를 지원해야 하고, 파일을 **실시간 속도(1배속)**로 흘려서 실제 통화 없이 파이프라인을 검증한다. 실제 통화 테스트는 단계 완성 시에만.
3. **AI 제안은 발화 종료 시점에만 생성** — 매 단어마다 갱신 금지 (비용/산만함).
4. **사이드톤 중복 주의** — 내 목소리가 전화기 회로를 타고 USB 채널에 희미하게 섞일 수 있음. 채널 간 중복 전사 제거 필요.
5. **API 키는 `.env`** — 코드/커밋에 절대 포함 금지.
6. **UI 텍스트는 한국어.**
7. **단계별 확인 후 진행 (중요, 반복 강조됨 — 절대 어기지 말 것)** — 한 청크가 끝나면 멈추고 결과를 보고한 뒤, 사용자 확인을 받고 나서 다음 청크 계획을 말한다. **계획을 "말하는 것"과 "시작해도 된다는 허락"은 별개다** — 계획을 설명한 뒤에는 반드시 멈추고, 사용자가 명시적으로 "시작해/해/가" 등 실행 지시를 줄 때까지 코드를 건드리지 않는다. 설계 컨펌을 받았다고 자동으로 다음 청크 구현에 들어가지 않는다.
   - **작업 시작 전 매번 [PLAN.md](PLAN.md)를 실제로 다시 읽는다** (읽었다고 가정하지 않는다). 지금 하려는 게 PLAN.md의 어느 청크인지, 순서가 맞는지 확인한 뒤 진행한다.
   - 청크 완료 시 PLAN.md의 상태 표기(⏳→✅)를 갱신한다.
8. **개발은 작게 쪼개고, 커밋은 사용자가 직접 (중요)** — 매 작업 단위마다:
   - 뭘 바꿨는지 / 어디(파일)를 바꿨는지 보고
   - 사용자가 직접 확인할 수 있는 체크리스트 제공 (사용자 입장 언어로)
   - 사용자 컨펌 후 `git add` → `commit` → `push` 명령어를 복붙용 블록으로 제공
   - Claude는 git 명령을 터미널에서 직접 실행하지 않는다. 사용자가 돌린다.
9. **설계가 개발보다 우선한다 (가장 중요)** — 개발은 수단이고, 설계(스키마·UI/UX·데이터 흐름)가 본질이다. 코드를 빨리 짜는 것보다 설계를 제대로 검증하는 게 먼저다.
   - 스키마/UI 변경이 필요한 요청이 들어오면, 코드부터 고치지 말고 설계 문서([DESIGN.md](DESIGN.md))부터 갱신하고 사용자 컨펌을 받는다.
   - 확정된 설계는 [DESIGN.md](DESIGN.md)에 기록한다. 대화가 길어지거나 세션이 바뀌어도 잊지 않도록, 결정과 그 이유(왜 이렇게 했는지)를 함께 남긴다.
   - "왜 이 프로젝트를 하는가"(실제 문제, 팀이 해결하려는 것)를 항상 먼저 확인하고, 그 목적에 비춰 설계를 검토한다. 개발 편의를 위해 설계를 타협하지 않는다.
10. **UI는 [STYLE.md](STYLE.md) 디자인 시스템을 무조건 따른다 (예외 없음)**
    - HTML/CSS를 한 줄이라도 쓰기 전에 STYLE.md 전체를 읽는다.
    - 색상은 STYLE.md에 정의된 토큰 값만 쓴다. 임의 hex 코드 금지.
    - 폰트: display는 세리프(Copernicus 대체 → Cormorant Garamond), body는 sans(StyreneB 대체 → Inter), 코드는 JetBrains Mono. 이 3분할을 깨지 않는다.
    - 컴포넌트(버튼/카드/배지 등)를 새로 만들기 전에 STYLE.md의 `Components` 섹션에 이미 있는지 먼저 확인하고, 있으면 그대로 재사용한다.
    - 작업 완료 후 STYLE.md의 `Do's and Don'ts`에 하나씩 대조해서 자체 점검한다.
    - STYLE.md에 없는 패턴(예: 실시간 상태 표시)이 필요하면, 조용히 임의로 만들지 말고 사용자에게 확인 후 STYLE.md에 추가하고 나서 구현한다.
    - STYLE.md는 원래 마케팅 사이트 기준이라 실시간 업무 화면과 상충하는 지점이 있다 (STYLE.md 하단 "nophone 적용 시 주의" 참고). 상충 지점을 발견하면 무시하지 말고 짚어서 확인받는다.
