"""python -m m30.pipeline 2026-10-16 --scenario scenarios/first_card.json  (로컬 DB 전용 개발 도구)"""

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from m30.adapters.fake import FakePriceSource, load_scenario
from m30.config import DB_URL_VAR, ConfigError, is_local_db, load_settings
from m30.db.store import CardStore, connect
from m30.pipeline.morning import MorningPipeline


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m m30.pipeline", description="가짜 시세 시나리오로 아침 파이프라인 실행")
    parser.add_argument("trading_day", type=date.fromisoformat, help="거래일 YYYY-MM-DD (동부 기준)")
    parser.add_argument("--scenario", type=Path, required=True, help="시나리오 JSON 경로")
    args = parser.parse_args(argv)

    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"{e}. 레포 루트에서 supabase start 후 README의 export 줄을 실행하세요", file=sys.stderr)
        return 2
    if not is_local_db(settings.database_url):
        # 가짜 카드를 쓰므로 원격 DB면 실험 데이터를 오염시킨다. 주소는 출력하지 않는다
        print(f"{DB_URL_VAR}이 로컬 DB가 아니라 중단합니다", file=sys.stderr)
        return 2

    scenario = load_scenario(args.scenario)
    with connect(settings) as conn:
        store = CardStore(conn)
        store.upsert_coverage(scenario.coverage)
        summary = MorningPipeline(prices=FakePriceSource(scenario), store=store).run(args.trading_day)
    delayed = ", ".join(summary.change_delayed) or "-"
    print(f"{summary.trading_day} cards_saved={summary.cards_saved} change_delayed={delayed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
