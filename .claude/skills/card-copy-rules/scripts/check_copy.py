#!/usr/bin/env python3
"""앱에 나가는 문장을 규칙으로 검사한다. 한 줄 = 문장 하나.

Usage:
    python3 check_copy.py --mode card  FILE   # 카드 줄, 시장 한눈에, 아침 알림
    python3 check_copy.py --mode arena FILE   # 아레나 토크
    echo "Apple rose 3%." | python3 check_copy.py --mode card -

Exit code: 0 = 위반 없음, 1 = 위반 있음. 스크립트가 못 잡는 규칙(사실/예측 구분,
근거 출처의 정확성)은 사람이나 copy-reviewer가 따로 판정한다.

검사 규칙과 금지어 목록은 backend/src/m30/copy_rules/에 한 벌만 있다. 이 스크립트는 그것을 불러 쓰는 실행기다.
"""

import argparse
import sys
from pathlib import Path

# 레포의 서버 패키지를 직접 불러 쓴다. copy_rules는 표준 라이브러리만 쓰므로 uv 없이 돈다
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend" / "src"))
from m30.copy_rules import check_arena, check_card  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["card", "arena"], required=True)
    parser.add_argument("file", help="검사할 파일. '-'이면 표준 입력")
    args = parser.parse_args()

    stream = sys.stdin if args.file == "-" else open(args.file, encoding="utf-8")
    check = check_card if args.mode == "card" else check_arena

    violations = 0
    for num, raw in enumerate(stream, 1):
        line = raw.strip()
        if not line or line.startswith("# "):  # "#NVDA ..." 같은 해시태그 문장은 검사한다
            continue
        issues = check(line)
        if issues:
            violations += 1
            print(f"[위반] {num}: {line}\n        → " + "; ".join(issues))
    print(f"\n위반 {violations}줄")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
