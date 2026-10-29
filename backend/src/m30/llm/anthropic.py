"""LLM 프로토콜의 실제 Anthropic 구현. 표준 라이브러리만 쓴다. 재시도는 하지 않는다(SourceCalls가 한다). system에 캐시 표시를 단다(#14). 토큰 수는 usage에서(#17).

키 노출 방지(2026-10-18 DB 비밀번호 사고와 같은 교훈): 키는 LLMSettings(repr 숨김) 안에만 있다. 헤더는 요청을 만드는
도우미 안에서만 만들고, 예외가 올라가는 complete 프레임의 지역 변수에 키·헤더를 두지 않는다(pytest --showlocals가 찍는다).
모든 실패는 상태만 담은 메시지로 from None — 원래 예외(urllib 프레임에 요청 헤더가 있다)를 끊는다."""

import http.client
import json
import urllib.error
import urllib.request

from m30.adapters import SourceError, TransientSourceError, error_for_status
from m30.config import LLMSettings
from m30.llm import LLMReply, LLMRequest

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicLLM:
    def __init__(self, settings: LLMSettings, *, url: str = API_URL, timeout: float = 30.0) -> None:
        if not url.startswith("https://"):  # HANDOFF 3-7: 외부 요청은 HTTPS. 키를 평문으로 보내지 않는다
            raise ValueError("url must start with https://")
        self._settings = settings
        self._url = url
        self._timeout = timeout

    def complete(self, request: LLMRequest) -> LLMReply:
        """응답의 text 블록을 이어 붙인 텍스트와 usage 토큰 수. 실패: 401·403 → AccessDeniedError, 429 → RateLimitedError, 5xx·타임아웃·
        접속 실패 → TransientSourceError, 그 밖의 HTTP 오류·이상한 응답 → SourceError."""
        try:
            with urllib.request.urlopen(self._http_request(request), timeout=self._timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as e:  # URLError의 하위 클래스라 먼저 받는다
            raise error_for_status("anthropic", e.code) from None
        except TimeoutError:
            raise TransientSourceError("anthropic timeout") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException):  # 접속 실패·응답 도중 끊김
            raise TransientSourceError("anthropic connection failed") from None
        try:
            data = json.loads(body)
            text = "".join(block["text"] for block in data["content"] if block["type"] == "text")
        except (ValueError, KeyError, TypeError):
            raise SourceError("anthropic response shape") from None
        usage = data.get("usage")  # data는 dict다(["content"]를 지났다)
        usage = usage if isinstance(usage, dict) else {}
        # 토큰 수 때문에 응답을 실패로 만들지 않는다: 빠졌거나 0 이상의 int가 아니면 0
        counts = [usage.get(k) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")]
        return LLMReply(text, *(n if type(n) is int and n >= 0 else 0 for n in counts))

    def _http_request(self, request: LLMRequest) -> urllib.request.Request:
        """헤더(키 포함)는 이 프레임 안에서만 만든다. Request의 repr에는 헤더가 없다."""
        payload = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            # Haiku 5.5는 기본이 적응형 사고: 답 크기로 잡은 max_tokens(200·50)를 사고에 다 쓰면 text 블록 없이 끝난다(#14)
            "thinking": {"type": "disabled"},
            # 캐시 표시: Haiku 5.5는 우리 지시문 길이에서도 캐시를 만들고 읽는다(#14 M0). 최소 길이보다 짧으면 API가 표시를 무시한다
            "system": [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": request.user}],
        }
        return urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode(),
            headers={"x-api-key": self._settings.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"},
            method="POST",
        )
