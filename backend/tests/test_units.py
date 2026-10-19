"""순수 함수 경계값. DB 없이 돈다."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from m30.adapters.prices import DailyBar
from m30.config import ET, ConfigError, is_local_db, load_settings
from m30.models import CardLine, LineStatus
from m30.pipeline.compute import change_pct, round_pct


def test_DB_주소가_없으면_변수_이름만_알려주고_멈춘다():
    with pytest.raises(ConfigError, match="SUPABASE_DB_URL"):
        load_settings({})


def test_설정을_출력해도_DB_비밀번호가_보이지_않는다():
    settings = load_settings({"SUPABASE_DB_URL": "postgresql://u:s3cret@127.0.0.1:54322/postgres"})
    assert "s3cret" not in repr(settings)


@pytest.mark.parametrize(
    "url, local",
    [
        ("postgresql://postgres:pw@127.0.0.1:54322/postgres", True),
        ("postgresql://postgres:pw@localhost:54322/postgres", True),
        ("postgresql://postgres:pw@[::1]:54322/postgres", True),
        ("host=127.0.0.1 port=54322 user=postgres", True),
        ("postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres", False),
        ("postgresql://postgres:pw@127.0.0.1.example.com:5432/postgres", False),
        ("postgresql://postgres:pw@/postgres", False),
    ],
)
def test_로컬_DB_주소만_로컬로_인정한다(url, local):
    assert is_local_db(url) is local


@pytest.mark.parametrize(
    "raw, shown",
    [("1.25", "1.3"), ("-1.25", "-1.3"), ("0.04", "0.0"), ("-0.04", "0.0"), ("0", "0.0")],
)
def test_등락률은_소수_첫째_자리에서_0에서_먼_쪽으로_반올림하고_음수_0은_없다(raw, shown):
    assert str(round_pct(Decimal(raw))) == shown


def bar(day, close):
    c = Decimal(close)
    return DailyBar(day=date(2026, 10, day), open=c, high=c, low=c, close=c, volume=1000, adjusted=True)


@pytest.mark.parametrize(
    "bars",
    [
        [bar(15, "180.00")],  # 봉 1개
        [bar(14, "0"), bar(15, "5.00")],  # 전일 종가 0
        [bar(14, "-1.00"), bar(15, "5.00")],  # 전일 종가 음수
    ],
    ids=["봉_1개", "전일_종가_0", "전일_종가_음수"],
)
def test_계산할_수_없으면_등락률을_만들지_않는다(bars):
    assert change_pct(bars) is None


def test_시간대_없는_확인_시각으로는_줄을_만들_수_없다():
    with pytest.raises(ValueError, match="checked_at"):
        CardLine("No new SEC filings found", LineStatus.CHECKED_NONE, datetime(2026, 10, 16, 7, 30), "SEC filings")


def test_출처_범위는_미지원_줄에서만_비울_수_있다():
    checked = datetime(2026, 10, 16, 7, 30, tzinfo=ET)
    assert CardLine("Not covered yet", LineStatus.UNSUPPORTED, checked, None).source_scope is None
    with pytest.raises(ValueError, match="source_scope"):
        CardLine("No new SEC filings found", LineStatus.CHECKED_NONE, checked, None)
