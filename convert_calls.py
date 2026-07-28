"""골든셋 변환기: sample/sample_call/*.md → replay 형식 (transcript.txt + briefing.txt).

품질 튜닝(TUNING.md)용. 실제 검수 통화 MD(원래입력 + 전문)를 suggest.py --replay가 먹는
형식으로 바꾼다. 변환 결과(.txt)는 실제 고객 내용이라 gitignore(sample/) — 이 스크립트만 커밋.

- '## 원래 입력' 섹션(하위 ## 헤더 포함, ## 녹취/요약/전문 전까지) → briefing
- '## 전문' 섹션: 'MM:SS 화자: 텍스트' 파싱 → 고객=고객, 그 외(이상민 등)=나,
  타임스탬프 제거, 같은 화자 연속 조각 병합(라이브 디바운스처럼)

사용:
    uv run convert_calls.py sample/sample_call/157018.md sample/golden
    # → sample/golden/157018.txt (+ 157018_briefing.txt)
    # 이후: uv run suggest.py --replay sample/golden/157018.txt --briefing-file sample/golden/157018_briefing.txt
"""
import re
import sys
from pathlib import Path

src = Path(sys.argv[1])
outdir = Path(sys.argv[2])
outdir.mkdir(parents=True, exist_ok=True)
text = src.read_text(encoding="utf-8")

# 원래입력 안에 ## 하위헤더(## 프로젝트 개요 등)가 있으므로, ## 녹취/요약/전문 전까지 통째로.
m = re.search(r"^## 원래 입력\s*\n(.*?)(?=^## (?:녹취|요약|전문)\b)", text, re.S | re.M)
briefing = m.group(1).strip() if m else ""
m = re.search(r"^## 전문\s*\n(.*)\Z", text, re.S | re.M)
jeonmun = m.group(1).strip() if m else ""

turns = []  # (speaker, text)
line_re = re.compile(r"^\d{1,2}:\d{2}\s*(.+?):\s*(.*)$")
for line in jeonmun.splitlines():
    m = line_re.match(line.strip())
    if not m:
        continue
    label, t = m.group(1).strip(), m.group(2).strip()
    if not t:
        continue
    speaker = "고객" if label == "고객" else "나"     # 고객 외(이상민 등)는 매니저=나
    if turns and turns[-1][0] == speaker:              # 연속 같은 화자 → 병합
        turns[-1] = (speaker, turns[-1][1] + " " + t)
    else:
        turns.append((speaker, t))

stem = src.stem
(outdir / f"{stem}.txt").write_text("\n".join(f"{sp}: {t}" for sp, t in turns), encoding="utf-8")
if briefing:
    (outdir / f"{stem}_briefing.txt").write_text(briefing, encoding="utf-8")

cust = sum(1 for sp, _ in turns if sp == "고객")
print(f"{stem}: 병합후 {len(turns)}턴 (고객 {cust}) · 브리핑 {len(briefing)}자")
