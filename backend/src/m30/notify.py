"""실패 알림(#17 D3): 운영 실행 요약을 Discord 웹훅으로 보낸다. 표준 라이브러리만(+ 같은 패키지의 리다이렉트 막기).

메시지는 CLI가 찍은 줄 그대로다(코드·건수·티커만, 공개 로그와 같은 규칙). 웹훅 주소는 비밀값이라 DiscordSettings(repr 숨김)
안에만 둔다: 지역 변수로 꺼내지 않고, 예외 메시지·주소를 읽지도 찍지도 않는다. 결과는 이유 코드로만 돌려준다."""

import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import date

from m30.adapters.edgar import _NoRedirect
from m30.config import DiscordSettings

DISCORD_LIMIT = 2000  # 메시지 content 최대 글자 수
USER_AGENT = "DiscordBot (https://github.com/Paul-sinn/market_in_30sec, 1)"  # Cloudflare가 기본 Python-urllib UA를 막을 수 있다

_OPENER = urllib.request.build_opener(_NoRedirect)  # 테스트가 패치한다. 리다이렉트는 따라가지 않는다(http_30x)


def discord_content(trading_day: date, exit_code: int, lines: Sequence[str]) -> str:
    """머리줄 + text 코드 블록(lines). 2000자를 넘으면 뒤 줄부터 빼고 블록 끝에 뺀 줄 수를 적는다(실패 배너는 맨 위라 남는다)."""
    head = f"{'**FAILED**' if exit_code else 'OK'} morning {trading_day} exit={exit_code}\n```text\n"
    kept = list(lines)
    body = "\n".join(kept)
    while len(head) + len(body) + len("\n```") > DISCORD_LIMIT:
        kept.pop()
        body = "\n".join([*kept, f"… {len(lines) - len(kept)} more lines (see Actions log)"])
    return f"{head}{body}\n```"


def send_discord(settings: DiscordSettings, content: str, *, timeout: float = 10.0) -> str | None:
    """POST 한 번(다시 시도하지 않는다). 2xx면 None, 아니면 이유 코드 "http_<상태>"|"timeout"|"connection"|"error".
    예외를 올리지 않는다: 알림 실패가 실행 결과(exit 코드)를 바꾸지 않게."""
    try:
        with _OPENER.open(_request(settings, content), timeout=timeout) as response:
            status = response.status
    except urllib.error.HTTPError as e:  # URLError의 하위 클래스라 먼저 받는다. 상태 코드만 읽는다
        return f"http_{e.code}"
    except TimeoutError:
        return "timeout"
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        return "connection"
    except Exception:
        return "error"
    return None if 200 <= status < 300 else f"http_{status}"


def _request(settings: DiscordSettings, content: str) -> urllib.request.Request:
    """주소는 이 프레임 안에서만 꺼낸다. Request의 repr에는 주소가 없다. @everyone·역할 멘션이 알림을 울리지 않게 멘션을 끈다."""
    return urllib.request.Request(
        settings.url,
        data=json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
