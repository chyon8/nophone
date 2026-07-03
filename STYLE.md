# STYLE.md — 디자인 시스템 (필수 준수)

> **이 문서는 nophone의 모든 UI 작업에 무조건 적용되는 단일 원본(source of truth)이다.** HTML/CSS를 작성하기 전에 반드시 이 문서를 먼저 읽는다. [CLAUDE.md](CLAUDE.md) 룰 10번 참고.

원본: Claude.com 디자인 시스템 (사용자 제공, 2026-07-03 확정)

## Overview

Claude.com is the warmest, most editorial interface in the AI-product category. The base atmosphere is a **tinted cream canvas** (`{colors.canvas}` — #faf9f5) — distinctly warm, deliberately not the cool gray-white that every other AI brand uses. Headlines run a **slab-serif display** ("Copernicus" / Tiempos Headline) at weight 400 with negative letter-spacing, paired with **StyreneB / Inter** body sans. The combination feels like a literary publication, not a SaaS marketing page.

Brand voltage comes from the **cream + coral pairing** — coral (`{colors.primary}` — #cc785c) is the signature Anthropic accent, used on every primary CTA, on the brand wordmark, and on full-bleed callout cards. The coral is warm, slightly muted, never cyan/blue — a deliberate counter-positioning against OpenAI's cool slate, Google's saturated blue, and Microsoft's corporate cyan.

The system has three surface modes that alternate page-by-page:
1. **Cream canvas** (`{colors.canvas}`) — default body floor
2. **Light cream cards** (`{colors.surface-card}`) — feature card backgrounds
3. **Dark navy product surfaces** (`{colors.surface-dark}`) — code editor mockups, model showcase cards, pre-footer CTAs, footer itself

The dark surfaces are where Claude shows its product chrome — code blocks, terminal output, model comparison tables, agentic-flow diagrams. The cream-to-dark contrast is the page's pacing rhythm.

**Key Characteristics:**
- Warm cream canvas (`{colors.canvas}` — #faf9f5) with dark warm-ink text (`{colors.ink}` — #141413). The brand's defining color choice.
- Coral primary CTA (`{colors.primary}` — #cc785c). Used scarcely on individual buttons, generously on full-bleed coral callout cards.
- Slab-serif display headlines via Copernicus / Tiempos Headline at weight 400 with negative letter-spacing. Pairs with humanist sans body for a literary editorial voice.
- Dark navy product mockup cards (`{colors.surface-dark}` — #181715) carrying code blocks, terminal panels, model comparison data — the brand shows the product chrome at scale rather than abstract marketing illustrations.
- Light cream feature cards (`{colors.surface-card}` — #efe9de) — slightly darker than canvas, used for content-driven feature explanations.
- Anthropic radial-spike mark — a small black asterisk-like glyph (4-spoke radial) — appears as the brand wordmark prefix and as a content marker.
- Border radius is hierarchical: `{rounded.md}` (8px) for buttons + inputs, `{rounded.lg}` (12px) for content + product cards, `{rounded.xl}` (16px) for the hero illustration container, `{rounded.pill}` for badges.
- Section rhythm `{spacing.section}` (96px) — modern-SaaS standard. Internal card padding stays generous at `{spacing.xl}` (32px).

## Colors

### Brand & Accent
- **Coral / Primary** (`{colors.primary}` — #cc785c): The signature Anthropic warm coral. Used on every primary CTA background, on full-bleed coral callout cards, on the brand wordmark accent.
- **Coral Active** (`{colors.primary-active}` — #a9583e): The press / hover-darker variant.
- **Coral Disabled** (`{colors.primary-disabled}` — #e6dfd8): A desaturated cream-tinted disabled state.
- **Accent Teal** (`{colors.accent-teal}` — #5db8a6): Used sparingly on secondary product surfaces (terminal status indicators, "active connection" dots).
- **Accent Amber** (`{colors.accent-amber}` — #e8a55a): Small companion warm-tone on category badges and inline highlights.

### Surface
- **Canvas** (`{colors.canvas}` — #faf9f5): The default page floor. Tinted cream.
- **Surface Soft** (`{colors.surface-soft}` — #f5f0e8): Section dividers, very-soft band backgrounds.
- **Surface Card** (`{colors.surface-card}` — #efe9de): Feature cards, content cards.
- **Surface Cream Strong** (`{colors.surface-cream-strong}` — #e8e0d2): Strongest-cream variant for selected tabs / emphasized bands.
- **Surface Dark** (`{colors.surface-dark}` — #181715): Code editor mockups, model showcase cards, footer.
- **Surface Dark Elevated** (`{colors.surface-dark-elevated}` — #252320): Elevated cards inside dark bands.
- **Surface Dark Soft** (`{colors.surface-dark-soft}` — #1f1e1b): Code block backgrounds inside larger dark cards.
- **Hairline** (`{colors.hairline}` — #e6dfd8): 1px border tone on cream surfaces.
- **Hairline Soft** (`{colors.hairline-soft}` — #ebe6df): Barely-visible divider.

### Text
- **Ink** (`{colors.ink}` — #141413): All headlines and primary text.
- **Body Strong** (`{colors.body-strong}` — #252523): Emphasized paragraphs, lead text.
- **Body** (`{colors.body}` — #3d3d3a): Default running-text color.
- **Muted** (`{colors.muted}` — #6c6a64): Sub-headings, breadcrumbs.
- **Muted Soft** (`{colors.muted-soft}` — #8e8b82): Captions, fine-print.
- **On Primary** (`{colors.on-primary}` — #ffffff): Text on coral buttons.
- **On Dark** (`{colors.on-dark}` — #faf9f5): Cream-tinted white on dark surfaces.
- **On Dark Soft** (`{colors.on-dark-soft}` — #a09d96): Secondary labels in dark mockups.

### Semantic
- **Success** (`{colors.success}` — #5db872)
- **Warning** (`{colors.warning}` — #d4a017)
- **Error** (`{colors.error}` — #c64545)

## Typography

### Font Family
**Copernicus** (또는 대체 **Tiempos Headline**) — slab-serif display, headline 전용. **StyreneB** (또는 대체 **Inter**) — humanist sans, body/UI 전용. **JetBrains Mono** — 코드 블록 전용.

Fallback stack: display `Tiempos Headline, Garamond, "Times New Roman", serif` / body `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`.

- Copernicus serif (weight 400, negative tracking) → h1, h2, h3, hero display
- StyreneB sans (weight 400-500) → body, navigation, buttons, captions, labels
- JetBrains Mono → 코드/터미널 텍스트

### Hierarchy

| Token | Size | Weight | Line Height | Letter Spacing | Use |
|---|---|---|---|---|---|
| `{typography.display-xl}` | 64px | 400 | 1.05 | -1.5px | 최상위 h1 — Copernicus |
| `{typography.display-lg}` | 48px | 400 | 1.1 | -1px | 섹션 헤드 |
| `{typography.display-md}` | 36px | 400 | 1.15 | -0.5px | 서브섹션 헤드 |
| `{typography.display-sm}` | 28px | 400 | 1.2 | -0.3px | 콜아웃 헤드라인 |
| `{typography.title-lg}` | 22px | 500 | 1.3 | 0 | 플랜/타이틀 라벨 — StyreneB |
| `{typography.title-md}` | 18px | 500 | 1.4 | 0 | 카드 제목 |
| `{typography.title-sm}` | 16px | 500 | 1.4 | 0 | 타일 제목, 리스트 라벨 |
| `{typography.body-md}` | 16px | 400 | 1.55 | 0 | 기본 본문 |
| `{typography.body-sm}` | 14px | 400 | 1.55 | 0 | 각주, 잔글씨 |
| `{typography.caption}` | 13px | 500 | 1.4 | 0 | 배지 라벨 |
| `{typography.caption-uppercase}` | 12px | 500 | 1.4 | 1.5px | 카테고리 태그 |
| `{typography.code}` | 14px | 400 | 1.6 | 0 | 코드 블록 — JetBrains Mono |
| `{typography.button}` | 14px | 500 | 1.0 | 0 | 버튼 라벨 |
| `{typography.nav-link}` | 14px | 500 | 1.4 | 0 | 상단 내비 메뉴 |

### Principles
Display는 항상 weight 400, 절대 bold 금지. Negative letter-spacing(-0.3~-1.5px)은 필수 — 없으면 브랜드 이탈로 읽힘. Body는 weight 400(본문)/500(라벨), humanist sans(geometric 금지).

### Font Substitute
Copernicus 대체: **Cormorant Garamond** weight 500, -0.02em tracking (1순위) / EB Garamond (2순위). StyreneB 대체: **Inter** (1순위) / Söhne (라이선스 있으면).

## Layout

- **Base unit**: 4px
- **Tokens**: `{spacing.xxs}` 4px · `{spacing.xs}` 8px · `{spacing.sm}` 12px · `{spacing.md}` 16px · `{spacing.lg}` 24px · `{spacing.xl}` 32px · `{spacing.xxl}` 48px · `{spacing.section}` 96px
- **Section padding**: 96px. **카드 내부 패딩**: 32px(피처/프라이싱/모델비교 카드), 24px(코드윈도우/커넥터 타일)
- **콜아웃/CTA 밴드**: 48px(코랄 카드), 64px(대형 다크 CTA)
- **Max content width**: ~1200px
- **그리드**: 피처 카드 3-up(desktop)/2-up(tablet)/1-up(mobile). 커넥터 타일 4~6-up/2-up/1-up. 프라이싱 3-up/1-up

## Elevation & Depth

색-블록 우선, 그림자는 드묾. 대부분의 깊이감은 cream vs dark 표면 대비에서 나옴.

| Level | Treatment | Use |
|---|---|---|
| Flat | 그림자/보더 없음 | 본문 섹션, 상단 내비, 히어로 밴드 |
| Soft hairline | 1px `{colors.hairline}` | 인풋, 서브내비, 일부 카드 |
| Cream card | `{colors.surface-card}` 배경, 그림자 없음 | 피처/콘텐츠 카드 |
| Dark surface card | `{colors.surface-dark}` 배경, 그림자 없음 | 코드 에디터 목업, 모델 쇼케이스 |
| Subtle drop shadow | 낮은 알파의 옅은 그림자 (드묾) | 호버-elevated 상태만 |

## Shapes — Border Radius

| Token | Value | Use |
|---|---|---|
| `{rounded.xs}` | 4px | 배지 악센트, 작은 드롭다운 |
| `{rounded.sm}` | 6px | 작은 인라인 버튼 |
| `{rounded.md}` | 8px | 표준 CTA 버튼, 텍스트 인풋, 탭 |
| `{rounded.lg}` | 12px | 콘텐츠/제품 카드 |
| `{rounded.xl}` | 16px | 히어로 일러스트 컨테이너 |
| `{rounded.pill}` | 9999px | 배지 필, "NEW" 태그 |
| `{rounded.full}` | 9999px/50% | 아바타, 아이콘 버튼 |

## Components (핵심)

- **`button-primary`**: 배경 `{colors.primary}`, 글자 `{colors.on-primary}`, `{typography.button}`, 패딩 12×20px, 높이 40px, `{rounded.md}`. Active: `{colors.primary-active}`.
- **`button-secondary`**: 배경 `{colors.canvas}`, 글자 `{colors.ink}`, 1px hairline 보더.
- **`button-secondary-on-dark`**: 배경 `{colors.surface-dark-elevated}`, 글자 `{colors.on-dark}`. 다크 위에서 절대 밝은 버튼으로 반전하지 않음.
- **`button-icon-circular`**: 36px 원형, 배경 `{colors.canvas}`, hairline 보더.
- **`text-link`**: 인라인 링크는 `{colors.primary}`(코랄).
- **`feature-card`**: 배경 `{colors.surface-card}`, `{rounded.lg}`, 패딩 32px.
- **`product-mockup-card-dark`**: 배경 `{colors.surface-dark}`, `{rounded.lg}`, 패딩 32px, 글자 `{colors.on-dark}`.
- **`code-window-card`**: 다크 카드, 내부 코드블록은 `{colors.surface-dark-soft}`, `{typography.code}`(JetBrains Mono), `{rounded.lg}`, 패딩 24px.
- **`callout-card-coral`**: 풀블리드 배경 `{colors.primary}`, 글자 `{colors.on-primary}`, `{rounded.lg}`, 패딩 48px.
- **`badge-pill`**: 배경 `{colors.surface-card}`, `{typography.caption}`, `{rounded.pill}`, 패딩 4×12px.
- **`badge-coral`**: 배경 `{colors.primary}`, 글자 `{colors.on-primary}`, `{typography.caption-uppercase}`, `{rounded.pill}`.
- **`text-input`**: 배경 `{colors.canvas}`, `{typography.body-md}`, `{rounded.md}`, 패딩 10×14px, 높이 40px, 1px hairline. Focus 시 코랄 3px 15%-알파 아웃링.
- **`category-tab` / `-active`**: 비활성 투명 배경+`{colors.muted}` 글자. 활성 `{colors.surface-card}` 배경+`{colors.ink}` 글자. 패딩 8×14px, `{rounded.md}`.
- **`footer`**: 배경 `{colors.surface-dark}`, 글자 `{colors.on-dark-soft}`. 절대 반전 안 함.

## Do's and Don'ts

### Do
- 모든 페이지는 cream canvas 바탕. 순백색 금지 — 웜톤이 브랜드 차별점.
- 모든 display 헤드라인은 세리프(Copernicus/대체 Cormorant Garamond) + negative tracking.
- `{colors.primary}`(코랄)는 프라이머리 CTA와 풀블리드 콜아웃에만. 여기저기 칠하지 않음.
- 실제 제품 크롬(코드/터미널/데이터)은 `product-mockup-card-dark` / `code-window-card`로 보여줌 — 추상 일러스트 대신.
- cream 카드와 dark 카드를 교차 배치해 리듬 형성.
- `{spacing.section}`(96px)을 섹션 간 기본 간격으로.

### Don't
- 쿨그레이/순백 캔버스 금지.
- 세리프 display를 bold로 쓰지 않음 (항상 400).
- 코랄 대신 파랑/시안 계열을 브랜드 악센트로 쓰지 않음.
- 코랄을 여러 요소에 남발하지 않음.
- Display 헤드라인에 sans(Inter 등) 쓰지 않음.
- 같은 표면 모드를 연속 두 밴드에 반복하지 않음.
- 호버 스타일을 시스템에 없는 걸로 추가하지 않음 (프라이머리는 press 시에만 어둡게, 그 외 변화 없음).

## nophone 적용 시 주의 (마케팅 사이트 → 실시간 업무 화면 전환 메모)

이 시스템은 원래 **마케팅 사이트**용이라, [DESIGN.md](DESIGN.md)에서 확정한 **통화 중 화면**(2초 안에 파악, 정보 밀도 높음)에 그대로 옮기면 아래 지점에서 조정이 필요하다. 무시하는 게 아니라 화면 구현 시 이 문서에 다시 물어보고 결정할 지점:

- **Display 세리프 대형 타이포**는 히어로용 크기(48~64px)라 통화 화면의 조밀한 자막/제안 텍스트엔 과함 → 화면 제목(예: "다음 멘트 제안") 정도에만 `{typography.title-md}~display-sm}` 세리프 적용, 본문 자막은 `{typography.body-md}` 사용
- **96px 섹션 리듬**은 화면 전체가 아니라 통화 화면 내부 두 컬럼(대화록/제안)의 여백 기준으로 축소 적용
- **다크 표면(`surface-dark`)**은 마침 통화 화면의 "AI 제안 실행 결과" 영역(코드윈도우 카드처럼 스트리밍 출력)에 자연스럽게 매칭됨 — 그대로 활용
- 실시간 상태 표시(●녹음중)는 이 시스템에 없는 패턴이라 `{colors.success}` 점 + `{colors.accent-teal}` 조합으로 새로 정의 필요 (화면 구현 시 STYLE.md에 추가)
