"""test_tiingo_guard가 하위 프로세스로만 돌리는 파일. test_ 접두사가 없어 기본 수집에서 빠진다. 실패하는 것이 정상이다.
TIINGO_API_KEY는 guard가 canary로 넣는다. api.tiingo.com으로는 아무 요청도 나가지 않는다(접속은 소켓 단계에서 거부)."""

import socket
import urllib.error
from datetime import date
from email.message import Message

from m30.adapters import tiingo
from m30.adapters.tiingo import TiingoPriceSource
from m30.config import load_tiingo_settings


def refuse(*args, **kwargs):
    raise ConnectionRefusedError("refused by tiingo_probe")


def test_접속이_거부된_Tiingo를_실제_urllib_경로로_부른다(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", refuse)  # DNS·접속 전에 막는다. urllib do_open 프레임까지 간다
    TiingoPriceSource(load_tiingo_settings()).daily_bars("AAPL", date(2025, 10, 10), date(2026, 10, 15))


class Denied:
    def open(self, request, timeout):
        headers = dict(request.header_items())  # 이 프레임에 Authorization이 있다. traceback에 이어지면 샌다
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", Message(), None)


def test_Tiingo가_401로_거부한다(monkeypatch):
    monkeypatch.setattr(tiingo, "_OPENER", Denied())
    TiingoPriceSource(load_tiingo_settings()).daily_bars("AAPL", date(2025, 10, 10), date(2026, 10, 15))
