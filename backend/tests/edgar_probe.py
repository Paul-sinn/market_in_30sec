"""test_edgar_guard가 하위 프로세스로만 돌리는 파일. test_ 접두사가 없어 기본 수집에서 빠진다. 실패하는 것이 정상이다.
SEC_USER_AGENT는 guard가 canary로 넣는다. sec.gov로는 아무 요청도 나가지 않는다(접속은 소켓 단계에서 거부)."""

import socket
import urllib.error
from email.message import Message

from m30.adapters import edgar
from m30.adapters.edgar import TICKERS_URL, EdgarClient
from m30.config import load_edgar_settings


def refuse(*args, **kwargs):
    raise ConnectionRefusedError("refused by edgar_probe")


def test_접속이_거부된_SEC를_실제_urllib_경로로_부른다(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", refuse)  # DNS·접속 전에 막는다. urllib do_open 프레임까지 간다
    client = EdgarClient(load_edgar_settings())
    client.get(TICKERS_URL)


class Denied:
    def open(self, request, timeout):
        headers = dict(request.header_items())  # 이 프레임에 User-Agent가 있다. traceback에 이어지면 샌다
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", Message(), None)


def test_SEC가_403으로_막는다(monkeypatch):
    monkeypatch.setattr(edgar, "_OPENER", Denied())
    EdgarClient(load_edgar_settings()).get(TICKERS_URL)
