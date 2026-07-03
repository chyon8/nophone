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

## 목표

유선 IP전화 통화를 실시간으로 보조하는 시스템.

- **1차 (현재)**: 통화 양쪽 음성을 실시간 STT → 웹 화면에 자막 표시 → AI가 다음 멘트 제안 → 프롬프트 버튼(견적 초안, 요구사항 정리, 절차 설명, 통화 요약) 즉시 실행
- **1.5차**: RAG — 과거 견적서/단가/절차 문서 기반 제안
- **2차 (나중)**: 내 목소리 클로닝 TTS로 AI가 직접 통화 (ElevenLabs)

**도메인**: IT 프로젝트 수주 상담 — 요구사항 파악, 견적, 개발 방향/절차 설명, 고객 질문 응대

## 하드웨어 (검증 완료)

- 상대방 목소리: IP전화기 헤드셋 포트 → 젠더/Y분배기 → USB 사운드카드 → 맥 입력
- 내 목소리: 맥북 내장 마이크
- 두 입력이 채널로 분리되어 화자 구분이 자동으로 됨

## 스택 (확정)

- Python 3.12 + uv / sounddevice (오디오 캡처) / OpenAI 스트리밍 전사 API (STT) / OpenAI GPT 스트리밍 (AI 제안) / FastAPI + WebSocket / 단일 HTML + 바닐라 JS / 파일 기반 저장 (JSON/Markdown)

## 개발 룰

1. **STT 모듈은 교체 가능하게 분리** — 전화 협대역 음질로 정확도가 부족하면 다른 엔진으로 갈아끼운다.
2. **테스트는 녹음 파일로** — 캡처 모듈은 `--source <file>` 모드를 지원해야 하고, 파일을 **실시간 속도(1배속)**로 흘려서 실제 통화 없이 파이프라인을 검증한다. 실제 통화 테스트는 단계 완성 시에만.
3. **AI 제안은 발화 종료 시점에만 생성** — 매 단어마다 갱신 금지 (비용/산만함).
4. **사이드톤 중복 주의** — 내 목소리가 전화기 회로를 타고 USB 채널에 희미하게 섞일 수 있음. 채널 간 중복 전사 제거 필요.
5. **API 키는 `.env`** — 코드/커밋에 절대 포함 금지.
6. **UI 텍스트는 한국어.**
