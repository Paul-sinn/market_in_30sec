"""순수 함수 경계값. DB 없이 돈다."""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from m30.adapters import AccessDeniedError, SourceError, TransientSourceError
from m30.adapters.events import Earnings, EarningsTiming, ExDividend
from m30.adapters.prices import DailyBar
from m30.config import ET, ConfigError, is_local_db, load_llm_settings, load_settings
from m30.copy_rules import ALWAYS_BANNED, CARD_BANNED, EMOTION_VERBS, SOURCE_TAG, check_card
from m30.llm.anthropic import AnthropicLLM, error_for_status
from m30.models import CardLine, LineStatus
from m30.pipeline.compute import card_numbers, change_pct, format_per_share, format_usd, round_pct, streak
from m30.pipeline.lines import (
    EVENT_WINDOW,
    REPLACEMENT_PHRASES,
    company_short_name,
    event_line,
    leverage_tag,
    price_fact_line,
    replacement_sentence,
)
from m30.pipeline.newsline import NEWS_TAG, NEWSLINE_SYSTEM, RETRY_NOTE, RETRY_REASONS, copy_retry_reasons, news_text
from m30.pipeline.review import FACTCHECK_SYSTEM, FactLabel, mask_names, name_terms, numbers_from_source, parse_factcheck_reply
from m30.trading_day import previous_trading_day

CHECKED = datetime(2026, 10, 16, 7, 30, tzinfo=ET)


def test_DB_주소가_없으면_변수_이름만_알려주고_멈춘다():
    with pytest.raises(ConfigError, match="SUPABASE_DB_URL"):
        load_settings({})


def test_설정을_출력해도_DB_비밀번호가_보이지_않는다():
    settings = load_settings({"SUPABASE_DB_URL": "postgresql://u:s3cret@127.0.0.1:54322/postgres"})
    assert "s3cret" not in repr(settings)


@pytest.mark.parametrize("env", [{}, {"ANTHROPIC_API_KEY": ""}], ids=["없음", "빈_값"])
def test_Anthropic_키가_없으면_변수_이름만_알려주고_멈춘다(env):
    with pytest.raises(ConfigError, match="^ANTHROPIC_API_KEY is not set$"):
        load_llm_settings(env)


def test_설정을_출력해도_Anthropic_키가_보이지_않는다():
    assert "sk-test-canary" not in repr(load_llm_settings({"ANTHROPIC_API_KEY": "sk-test-canary"}))


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


@pytest.mark.parametrize(
    "day, previous",
    [((10, 19), (10, 16)), ((10, 13), (10, 12)), ((10, 17), (10, 16)), ((10, 18), (10, 16))],
    ids=["월요일", "화요일", "토요일", "일요일"],
)
def test_직전_거래일은_주말을_건너뛴다(day, previous):
    assert previous_trading_day(date(2026, *day)) == date(2026, *previous)


def ohlc(day, close):
    c = Decimal(close)
    return DailyBar(day=day, open=c, high=c, low=c, close=c, volume=1000, adjusted=True)


def week52(last_close, first_day=date(2025, 10, 16)):
    """마지막 봉 2026-10-15. 2026-10-15 − 52주 = 2025-10-16. 고점 100, 저점 80(25% 아래라 근처 아님)."""
    days_closes = [(first_day, "100"), (date(2026, 3, 2), "80"), (date(2026, 6, 1), "100"), (date(2026, 10, 14), "100"),
                   (date(2026, 10, 15), last_close)]
    return [ohlc(d, c) for d, c in days_closes]


@pytest.mark.parametrize(
    "last_close, text",
    [("100", "At 52-week high"), ("99.96", "At 52-week high"), ("99.95", "0.1% below 52-week high")],
    ids=["정확히_같음", "0.04%_아래는_0.0", "0.05%_아래는_0.1"],
)
def test_52주_고점과_정확히_같거나_반올림해_0_0이면_At_52_week_high다(last_close, text):
    assert price_fact_line(week52(last_close), CHECKED).text == text


@pytest.mark.parametrize(
    "first_day, text",
    [(date(2025, 10, 16), "At 52-week high"), (date(2025, 10, 17), "No additional price highlights")],
    ids=["52주_전_날부터_있음", "하루_모자람"],
)
def test_52주_사실은_마지막_봉_52주_전까지_이력이_있어야_쓴다(first_day, text):
    assert price_fact_line(week52("100", first_day), CHECKED).text == text


@pytest.mark.parametrize(
    "last_close, text",
    [
        ("90", "10.0% below 52-week high"),  # (100 − 90) / 100, 저점 80에서 12.5% 위
        ("89.9", "No additional price highlights"),  # 고점에서 10.1% 아래, 저점에서 12.4% 위
        ("88", "10.0% above 52-week low"),  # (88 − 80) / 80, 고점에서 12.0% 아래
        ("88.08", "No additional price highlights"),  # 저점에서 10.1% 위, 고점에서 11.9% 아래
    ],
    ids=["고점_10.0%", "고점_10.1%", "저점_10.0%", "저점_10.1%"],
)
def test_52주_고점·저점_거리는_10_0퍼센트까지_가격_사실이다(last_close, text):
    assert price_fact_line(week52(last_close), CHECKED).text == text


@pytest.mark.parametrize(
    "closes, text",
    [
        (["101", "100", "101", "102"], "No additional price highlights"),
        (["101", "100", "101", "102", "103"], "Up 3 days in a row"),
        (["99", "100", "99", "98"], "No additional price highlights"),
        (["99", "100", "99", "98", "97"], "Down 3 days in a row"),
    ],
    ids=["상승_2일", "상승_3일", "하락_2일", "하락_3일"],
)
def test_연속_상승·하락은_3일부터_가격_사실이다(closes, text):
    bars = [ohlc(date(2026, 10, 12) + timedelta(days=i), c) for i, c in enumerate(closes)]  # 52주 이력 없음
    assert price_fact_line(bars, CHECKED).text == text


@pytest.mark.parametrize(
    "closes, days",
    [
        (["100", "101", "102", "103"], 3),
        (["103", "102", "101", "100"], -3),
        (["100", "101", "102", "102"], 0),
        (["100", "101", "102", "102.04"], 0),  # +0.039% → 0.0% 보합
        (["100", "101", "102", "102.06"], 3),  # +0.059% → 0.1% 상승
        (["100", "101", "101", "102"], 1),
    ],
    ids=["상승_3일", "하락_3일", "마지막_날_보합", "반올림_0.0은_보합", "반올림_0.1은_상승", "중간_보합에서_끊김"],
)
def test_연속_일수는_반올림해서_0_0퍼센트인_날에_끊긴다(closes, days):
    assert streak([ohlc(date(2026, 10, 12) + timedelta(days=i), c) for i, c in enumerate(closes)]) == days


TUE, FRI = date(2026, 10, 13), date(2026, 10, 16)


@pytest.mark.parametrize(
    "event, status",
    [
        (Earnings(TUE + EVENT_WINDOW, True, None), LineStatus.CHECKED_FOUND),
        (Earnings(TUE + EVENT_WINDOW + timedelta(days=1), True, None), LineStatus.CHECKED_NONE),
        (ExDividend(TUE - timedelta(days=1), Decimal("0.51")), LineStatus.CHECKED_NONE),
    ],
    ids=["기간_마지막_날", "기간_다음_날", "지난_일정"],
)
def test_일정은_거래일부터_표시_기간_끝까지만_고른다(event, status):
    assert event_line([event], TUE, CHECKED).status is status  # 어댑터가 범위를 어겨도 줄은 범위를 지킨다


def test_D_N은_달력일로_센다():
    line = event_line([Earnings(date(2026, 10, 19), True, EarningsTiming.BEFORE_OPEN)], FRI, CHECKED)
    assert line.text == "Earnings Mon 10/19 before open (D-3)"  # 거래일로 세면 D-1


def test_추정_실적일의_est는_발표_시점_뒤_D_N_앞에_온다():
    line = event_line([Earnings(date(2026, 10, 15), False, EarningsTiming.AFTER_CLOSE)], TUE, CHECKED)
    assert line.text == "Earnings Thu 10/15 after close (est.) (D-2)"


@pytest.mark.parametrize(
    "leverage, tag",
    [
        ("3.00", "3x · resets daily"),
        ("-3.00", "−3x inverse · resets daily"),  # U+2212 진짜 마이너스
        ("1.50", "1.5x · resets daily"),
        ("-1.00", "−1x inverse · resets daily"),
        ("10.00", "10x · resets daily"),  # 1E+1 표기가 나오지 않는다
        (None, None),
    ],
    ids=["3배", "인버스_3배", "1.5배", "인버스_1배", "10배", "레버리지_상품_아님"],
)
def test_레버리지_태그는_배율과_방향에서_만든다(leverage, tag):
    assert leverage_tag(None if leverage is None else Decimal(leverage)) == tag


@pytest.mark.parametrize(
    "amount, shown",
    [
        ("0.70", "$0.70"),
        ("1.5", "$1.50"),
        ("0.51", "$0.51"),
        ("0.2475", "$0.2475"),
        ("0.00456", "$0.0046"),
        ("0.00015", "$0.0002"),  # 넷째 자리 반올림은 0에서 먼 쪽
        ("0.00025", "$0.0003"),  # 짝수 쪽 반올림(ROUND_HALF_EVEN)이면 $0.0002
        ("0.99995", "$1.00"),
        ("0.24741", "$0.2474"),  # 항상 올림(ROUND_UP·ROUND_CEILING)이면 $0.2475
        ("0.24745", "$0.2475"),  # 0에서 먼 쪽. 짝수 쪽이면 $0.2474
    ],
)
def test_주당_금액은_센트까지_쓰고_발표값을_반올림해_없애지_않는다(amount, shown):
    assert format_per_share(Decimal(amount)) == shown


@pytest.mark.parametrize(
    "amount, shown",
    [("0.0001", "$0.0001"), ("0.000099", "<$0.0001"), ("0.00009999", "<$0.0001"), ("0.00005", "<$0.0001")],
    ids=["정확히_0.0001", "0.0001_바로_아래", "0.0001에_더_가까운_아래", "반올림하면_0.0001이_되는_값"],
)
def test_주당_금액이_0보다_크고_0_0001달러_미만이면_반올림하지_않고_작다고_표시한다(amount, shown):
    assert format_per_share(Decimal(amount)) == shown


@pytest.mark.parametrize(
    "amount, shown",
    [
        (94_000_000_000, "$94B"),
        (94_300_000_000, "$94.3B"),
        (1_200_000, "$1.2M"),
        (1_250_000, "$1.3M"),
        (999_940_000, "$999.9M"),
        (999_950_000, "$1B"),  # 반올림하면 1000M → 다음 단위
        (1_200_000_000_000, "$1.2T"),
        (950_000, "$950K"),
        (950, "$950"),
    ],
)
def test_큰_금액은_단위로_축약하고_소수_첫째_자리까지_쓴다(amount, shown):
    assert format_usd(Decimal(amount)) == shown


@pytest.mark.parametrize("fmt, amount", [(format_usd, "-1"), (format_per_share, "0"), (format_per_share, "-0.5")])
def test_음수_금액이나_0_이하_주당_금액은_표기하지_않는다(fmt, amount):
    with pytest.raises(ValueError):
        fmt(Decimal(amount))


@pytest.mark.parametrize(
    "text, shown, numbers",
    [
        ("$94.0 billion", "$94B", ("$94B",)),
        ("$1.2bn", "$1.2B", ("$1.2B",)),
        ("$3 thousand", "$3K", ("$3K",)),
        ("$7 mm", "$7M", ("$7M",)),
        ("US$5 million", "US$5M", ("$5M",)),
        ("$0.5 billion", "$500M", ("$500M",)),
        ("$1,500 million", "$1.5B", ("$1.5B",)),
        ("$0.2475 per share", "$0.2475 per share", ("$0.2475",)),
        ("$0.26 a share", "$0.26 a share", ("$0.26",)),
        ("$0.00 per share", "#", ()),
        ("$ 102,466 $ 94,930", "# #", ()),  # "(In millions)" 표: 단위를 모르면 1,000배 틀린 값이 된다
        ("$25.5 to $26.0 billion", "$25.5B to $26B", ("$25.5B", "$26B")),
        ("between $90 and $93 billion", "between $90B and $93B", ("$90B", "$93B")),
        ("$1.0-1.2 billion", "$1B-$1.2B", ("$1B", "$1.2B")),
        ("1.25%", "1.3%", ("1.3%",)),
        ("12 percent", "12.0%", ("12.0%",)),
        ("5 to 7%", "5.0% to 7.0%", ("5.0%", "7.0%")),
        ("5-7%", "5.0%-7.0%", ("5.0%", "7.0%")),
        ("in 2025 to 8%", "in # to 8.0%", ("8.0%",)),  # 정수 부분 4자리는 범위의 앞값이 아니다
        ("5 and 7%", "# and 7.0%", ("7.0%",)),
        ("Item 2.02 - 5%", "Item # - 5.0%", ("5.0%",)),  # 공백 낀 대시는 연결어가 아니다
        ("-8%", "-8.0%", ("8.0%",)),
        ("FY2026", "FY#", ()),
        ("Q3", "Q3", ()),
        ("3.5x", "#x", ()),
        ("October 15, 2026", "October #, #", ()),
        ("Form 8-K", "Form #-K", ()),
        ("$5 billion and $5.0 billion", "$5B and $5B", ("$5B",)),
        ("8% then $2 billion", "8.0% then $2B", ("8.0%", "$2B")),
    ],
)
def test_원문_금액·퍼센트는_카드_표기로_바꾸고_나머지_숫자는_가린다(text, shown, numbers):
    assert card_numbers(text, 4000) == (shown, False, numbers)


@pytest.mark.parametrize(
    "text, shown, numbers",
    [
        ("$" + "9" * 23 + " million", "#", ()),
        ("$" + "9" * 17 + " trillion", "#", ()),
        ("$" + "9" * 25 + " per share", "#", ()),
        ("9" * 28 + "%", "#", ()),
        ("9" * 28 + " percent", "#", ()),
        ("$1 to $" + "9" * 20 + " billion", "$1B to #", ("$1B",)),  # 표기할 수 있는 쪽만 계산된 값
    ],
    ids=["백만_23자리", "조_17자리", "주당_25자리", "퍼센트_28자리", "percent_28자리", "범위_한쪽"],
)
def test_표기할_수_없을_만큼_긴_숫자는_예외_없이_가린다(text, shown, numbers):
    assert card_numbers(text, 4000) == (shown, False, numbers)  # Decimal 정밀도(28자리)를 넘으면 반올림할 수 없다


@pytest.mark.parametrize(
    "max_chars, result",
    [
        (15, ("Revenue was ", True, ())),  # 15자는 $102.5B(12~19자) 가운데: 값의 시작에서 자른다
        (19, ("Revenue was $102.5B", True, ("$102.5B",))),
        (24, ("Revenue was $102.5B toda", True, ("$102.5B",))),
        (25, ("Revenue was $102.5B today", False, ("$102.5B",))),
    ],
)
def test_자를_때_바꾼_숫자를_쪼개지_않고_잘린_값은_목록에서_뺀다(max_chars, result):
    # 바꾼 뒤 길이로 잰다: 원문을 먼저 자르면 $102.5 billion이 단위 없는 $102.5로 남는다
    assert card_numbers("Revenue was $102.5 billion today", max_chars) == result


def test_첫_번째_줄_출처_꼬리표는_문구_검사기의_꼬리표_목록에_있다():
    assert SOURCE_TAG.search(f"x ({NEWS_TAG})")  # 목록 밖이면 검사기가 꼬리표를 단어 수에 센다


def test_첫_번째_줄_지시문이_이름_붙인_금지어는_카드_금지어_목록에_있다():
    found = re.search(r"Do not use the words (.+?), even when the filing does\.", NEWSLINE_SYSTEM)
    assert found, "지시문에 금지어 문장이 없다"
    words = re.split(r", (?:or )?", found[1])
    assert words and set(words) <= set(CARD_BANNED)  # card.toml에서 빠진 단어를 지시문만 계속 막지 않게


@pytest.mark.parametrize(
    "status, error",
    [(401, AccessDeniedError), (403, AccessDeniedError), (429, TransientSourceError), (500, TransientSourceError),
     (503, TransientSourceError), (529, TransientSourceError), (400, SourceError), (404, SourceError)],
)
def test_Anthropic_HTTP_상태는_재시도·차단·기타_실패로_나뉜다(status, error):
    raised = error_for_status(status)
    assert type(raised) is error  # 400·404는 SourceError 그 자체: 재시도도 차단도 하지 않는다
    assert str(raised) == f"anthropic http {status}"  # 상태만. 응답 본문·헤더·URL 없음


def test_Anthropic_클라이언트는_HTTPS_주소만_받는다():
    with pytest.raises(ValueError, match="https"):
        AnthropicLLM(load_llm_settings({"ANTHROPIC_API_KEY": "k"}), url="http://api.anthropic.com/v1/messages")


@pytest.mark.parametrize(
    "items, amended, shown",
    [
        (("2.02", "9.01"), False, "Apple reported quarterly results"),
        (("5.02",), False, "Apple announced a leadership update"),  # 이사 변화·임원 보수만 다룬 5.02에도 참
        (("1.01",), False, "Apple signed a major agreement"),
        (("2.01",), False, "Apple completed an acquisition or sale"),
        (("8.01",), False, "Apple filed a company update"),
        ((), False, "Apple filed a company update"),
        (("5.02", "2.02"), False, "Apple reported quarterly results"),  # 항목이 여럿이면 표 순서(2.02 먼저)
        (("5.02",), True, "Apple updated an earlier report"),  # 8-K/A는 항목과 관계없이
    ],
    ids=["2.02와_9.01", "5.02", "1.01", "2.01", "그_외", "항목_없음", "우선순위", "정정_공시"],
)
def test_대체_줄은_8_K_항목으로_소식_종류만_밝힌다(items, amended, shown):
    assert replacement_sentence("Apple Inc.", items, amended) == shown


@pytest.mark.parametrize(
    "name, short",
    [("Apple Inc.", "Apple"), ("Best Buy Co., Inc.", "Best Buy"), ("3M Company", "3M"),
     ("The Coca-Cola Company", "Coca-Cola"), ("Microsoft Corporation", "Microsoft"), ("Alphabet Inc.", "Alphabet"),
     ("JPMorgan Chase & Co.", "JPMorgan Chase"), ("Inc.", "Inc."), ("Eli Lilly and Company", "Eli Lilly"),
     ("Johnson & Johnson", "Johnson & Johnson"), ("Merck & Co., Inc.", "Merck")],
)
def test_짧은_회사_이름은_앞_The와_끝_법인_꼬리를_뗀다(name, short):
    assert company_short_name(name) == short


def test_종목명을_가리고_검사하면_이름_속_금지어는_통과하고_이름_밖은_차단한다():
    terms = name_terms(["BBY"], {"BBY": "Best Buy Co., Inc."})

    assert {"Best Buy Co., Inc.", "Best Buy", "BBY"} <= set(terms)
    assert check_card(mask_names("Best Buy announced a new CFO. (Company)", terms)) == []
    assert check_card(mask_names("Best Buy agreed to buy a startup (SEC filing)", terms)) == ["금지어 'buy'"]
    assert mask_names("Best Buy's CFO", terms) == "Name Name's CFO"  # 단어마다 한 단어: 단어 수 그대로
    assert mask_names("Pineapple", name_terms(["AAPL"], {"AAPL": "Apple Inc."})) == "Pineapple"  # 단어 안은 가리지 않는다
    # 대소문자 그대로: 이름과 글자가 같은 소문자 말(best buy)은 이름이 아니다
    assert check_card(mask_names("Best Buy called the TV a best buy (Company)", terms)) == ["금지어 'buy'"]


@pytest.mark.parametrize(
    "numbers, sentence, ok",
    [
        (("$94B",), "Apple reported Q3 revenue of $94.0B", True),
        (("1.3%",), "revenue rose 1.25%", True),
        (("8.0%",), "revenue fell 8 percent", True),
        (("$1.64",), "EPS of $1.64 per diluted share", True),
        (("8.0%",), "revenue fell -8.0%", True),
        (("$5B",), "Name reported Q3 revenue of $5B", True),
        ((), "Apple reported Q3 results", True),
        (("$102.5B",), "revenue of $103B", False),
        (("$102.5B",), "revenue rose in 2026", False),
        ((), "Apple filed an 8-K", False),
        ((), "Apple named 3 directors", False),
        (("$1.64",), "EPS of $1.64", False),  # 단위 없는 금액은 닫힌 쪽(#6 U1)
        ((), "Apple named a CFO +2 More", False),
    ],
    ids=["$94.0B", "1.25%", "8_percent", "주당", "음수_부호", "가린_이름", "숫자_없음", "다른_금액", "연도", "서식_이름",
         "개수", "단위_없는_금액", "대문자_More"],
)
def test_숫자_대조는_계산_단계와_같은_표기로_바꿔_비교한다(numbers, sentence, ok):
    assert numbers_from_source(sentence, numbers) is ok


@pytest.mark.parametrize(
    "text, label",
    [
        ('{"label": "fact"}', FactLabel.FACT),
        ('```json\n{"label": "fact"}\n```\n', FactLabel.FACT),
        ('{"label": "forecast", "why": "x"}', FactLabel.FORECAST),  # 다른 키는 무시
        ('{"label": "opinion"}', FactLabel.OPINION),
        ('{"label": "Fact"}', None),
        ('{"label": null}', None),
        ("[]", None),
        ('"fact"', None),
        ("", None),
        ("x", None),
    ],
    ids=["fact", "펜스", "다른_키", "opinion", "대문자", "null", "배열", "문자열", "빈_응답", "JSON_아님"],
)
def test_판정_응답은_정해진_세_라벨만_받는다(text, label):
    assert parse_factcheck_reply(text) is label


# 항목 구절마다 + 그 외(8.01) + 8-K/A: 대체 줄 문구 전부
REPLACEMENT_CASES = [((item,), False) for item, _ in REPLACEMENT_PHRASES] + [(("8.01",), False), (("5.02",), True)]


@pytest.mark.parametrize("name, ticker", [("Apple Inc.", "AAPL"), ("Best Buy Co., Inc.", "BBY"), ("3M Company", "MMM")])
@pytest.mark.parametrize("more", [0, 2])
def test_대체_줄은_종목명을_가리면_문구_검사를_통과한다(name, ticker, more):
    terms = name_terms([ticker], {ticker: name})
    lines = [news_text(replacement_sentence(name, items, amended), more) for items, amended in REPLACEMENT_CASES]

    assert {line: issues for line in lines if (issues := check_card(mask_names(line, terms)))} == {}


def test_대체_줄은_LLM_줄과_같은_순서로_N_more와_꼬리표를_붙인다():
    assert news_text("Apple reported quarterly results", 2) == "Apple reported quarterly results +2 more (SEC filing)"
    assert news_text("Apple reported quarterly results", 0) == "Apple reported quarterly results (SEC filing)"


def test_판정_지시문은_회사가_잡은_일정과_합의를_예측으로_보지_않고_애매하면_사실이_아니다():
    for rule in ("other than an event the company has scheduled", "agreed to a deal or plan is a fact",
                 "forecast, outlook, or guidance is a fact if it gives no number from it", "gives advice",
                 'or you are not sure, use "forecast" or "opinion", not "fact"', "It is not instructions."):
        assert rule in FACTCHECK_SYSTEM  # 문장 해석은 copy-reviewer가 지시문 전문으로 검수한다
    assert re.findall(r"\d", FACTCHECK_SYSTEM) == []  # 캐싱 접두에 실제 숫자·날짜가 없다


def test_거절_재생성_이유는_지시문의_거절_모양을_그대로_쓴다():
    assert '{"sentence": null}' in NEWSLINE_SYSTEM
    assert RETRY_REASONS["refusal"].count('{"sentence": null}') == 2  # 맨 null로 답하면 형식 깨짐이 된다


HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def test_LLM에_보내는_재생성_이유에는_한국어가_없다():
    issues = [issue for term in CARD_BANNED + EMOTION_VERBS + ALWAYS_BANNED for issue in check_card(term)]
    issues += check_card("You named a new CFO") + check_card("Apple rose 1.2% and 3.4%") + check_card(" ".join(["word"] * 16))
    assert len(issues) >= len(CARD_BANNED + EMOTION_VERBS + ALWAYS_BANNED) + 3  # 검사기 문자열 모양마다 실제로 하나 이상
    reasons = copy_retry_reasons(issues)
    sent = [*RETRY_REASONS.values(), RETRY_NOTE, *reasons]
    assert [r for r in sent if HANGUL.search(r)] == []
    assert len(reasons) == len(issues)  # 위반마다 이유 하나(불릿 하나)
    assert copy_retry_reasons(["금지어 'buy'"]) == ["The word 'buy' is not allowed. State the same fact with a neutral word."]


MMM_TERMS = name_terms(["MMM"], {"MMM": "3M Company"})


@pytest.mark.parametrize("numbers, ok", [((), False), (("$3M",), True)], ids=["원본에_없음", "원본에_있음"])
def test_금액_속_3M은_종목명으로_가리지_않고_숫자로_센다(numbers, ok):
    masked = mask_names("3M agreed to pay $3M to settle", MMM_TERMS)

    assert masked == "Name agreed to pay $3M to settle"
    assert numbers_from_source(masked, numbers) is ok


def test_이름_3M은_그대로_가려진다():
    assert mask_names("3M reported Q3 revenue of $5B", MMM_TERMS) == "Name reported Q3 revenue of $5B"


def test_종목명은_단어_전체일_때만_가린다():
    terms = name_terms(["AAPL", "BBY"], {"AAPL": "Apple Inc.", "BBY": "Best Buy Co., Inc."})

    assert mask_names("PineApple Applesauce xBBY BBYx", terms) == "PineApple Applesauce xBBY BBYx"  # 앞·뒤 경계 각각
    assert mask_names("(BBY) Apple's", terms) == "(Name) Name's"
