"""골든셋 변환기: 실제 검수 통화 MD → replay 형식 (transcript.txt + briefing.txt [+ posting.txt]).

품질 튜닝·평가(eval_turns.py)용. 실제 검수 통화 MD(원래입력 + 전문)를 suggest.py --replay가 먹는
형식으로 바꾼다. 변환 결과(.txt)는 실제 고객 내용이라 gitignore(sample/) — 이 스크립트만 커밋.

- '## 원래 입력' 섹션(하위 ## 헤더 포함, ## 녹취/요약/전문 전까지) → briefing
- '## 전문' 섹션: 'MM:SS 화자: 텍스트' 파싱 → 고객=고객, 그 외(이상민 등)=나,
  타임스탬프 제거, 같은 화자 연속 조각 병합(라이브 디바운스처럼)
- 화자 라벨 뒤바뀜 자동 교정: 녹취를 만든 AI가 매니저를 '고객'으로 찍는 경우가 있다(47건 중 5건).
  첫 몇 줄에서 "위시켓입니다/위시켓 ○○○입니다/위시켓이라고 합니다"라고 자기소개한 쪽이 '고객'이면 뒤집는다.
- 옆에 {id}_posting.md(실제 등록 공고)가 있으면 {id}_posting.txt로 같이 복사한다.

사용:
    uv run convert_calls.py ~/Desktop/call-samples/*.md sample/calls      # 여러 개 (_posting.md는 자동 제외)
    uv run convert_calls.py sample/sample_call/157018.md sample/golden    # 1개
"""
import re
import sys
from pathlib import Path

# 매니저 자기소개: "위시켓입니다" "위시켓 이상민입니다" "여기 위시켓이라고 합니다" "위시켓의 장수룡이라고 합니다"
INTRO_RE = re.compile(r"위시켓(?:의)?\s?(?:[가-힣]{2,4})?(?:입니다|이라고\s?합니다)")
LINE_RE = re.compile(r"^(?:\d{1,2}:\d{2}\s*)?([^:]{1,12}):\s*(.*)$")  # 타임스탬프 없는 전문(156987)도 파싱


def convert(src: Path, outdir: Path):
    text = src.read_text(encoding="utf-8")

    # 원래입력 안에 ## 하위헤더(## 프로젝트 개요 등)가 있으므로, ## 녹취/요약/전문 전까지 통째로.
    m = re.search(r"^## 원래 입력\s*\n(.*?)(?=^## (?:녹취|요약|전문)\b)", text, re.S | re.M)
    briefing = m.group(1).strip() if m else ""
    m = re.search(r"^## 전문\s*\n(.*)\Z", text, re.S | re.M)
    jeonmun = m.group(1).strip() if m else ""

    lines = []  # (label, text)
    for line in jeonmun.splitlines():
        m = LINE_RE.match(line.strip())
        if m and m.group(2).strip():
            lines.append((m.group(1).strip(), m.group(2).strip()))

    intro = next((label for label, t in lines[:8] if INTRO_RE.search(t)), None)
    swapped = intro == "고객"

    turns = []  # (speaker, text)
    for label, t in lines:
        is_customer = (label == "고객") != swapped
        speaker = "고객" if is_customer else "나"     # 고객 외(이상민 등)는 매니저=나
        if turns and turns[-1][0] == speaker:         # 연속 같은 화자 → 병합
            turns[-1] = (speaker, turns[-1][1] + " " + t)
        else:
            turns.append((speaker, t))

    stem = src.stem
    (outdir / f"{stem}.txt").write_text("\n".join(f"{sp}: {t}" for sp, t in turns), encoding="utf-8")
    if briefing:
        (outdir / f"{stem}_briefing.txt").write_text(briefing, encoding="utf-8")
    posting = src.with_name(f"{stem}_posting.md")
    if posting.exists():
        (outdir / f"{stem}_posting.txt").write_text(posting.read_text(encoding="utf-8"), encoding="utf-8")

    cust = sum(1 for sp, _ in turns if sp == "고객")
    note = " · ⚠ 화자 라벨 뒤바뀜 → 교정함" if swapped else ""
    print(f"{stem}: 병합후 {len(turns)}턴 (고객 {cust}) · 브리핑 {len(briefing)}자"
          f"{' · 공고 있음' if posting.exists() else ''}{note}")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    *srcs, out = sys.argv[1:]
    outdir = Path(out)
    outdir.mkdir(parents=True, exist_ok=True)
    for s in srcs:
        p = Path(s)
        if p.stem.endswith("_posting"):
            continue
        convert(p, outdir)


if __name__ == "__main__":
    main()
