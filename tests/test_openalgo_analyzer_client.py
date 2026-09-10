from __future__ import annotations

import json

import pytest

from src.oracle.paper_autopilot import (
    OpenAlgoAnalyzerClient,
    OracleExecutionBlocked,
    OracleExecutionUnavailable,
    OraclePaperAutopilot,
)


class Response:
    def __init__(
        self,
        *,
        status_code=200,
        content_type="application/json",
        body=None,
        malformed=False,
    ):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.body = body
        self.malformed = malformed

    def json(self):
        if self.malformed:
            raise ValueError("malformed")
        return self.body


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def analyzer_body(*, enabled=True, mode="analyze"):
    return {
        "status": "success",
        "data": {"analyze_mode": enabled, "mode": mode},
    }


def client(
    response,
    api_key="configured-secret",
    base_url="http://127.0.0.1:5001",
):
    session = Session(response)
    return (
        OpenAlgoAnalyzerClient(
            base_url,
            api_key,
            session=session,
        ),
        session,
    )


def test_valid_analyzer_json_uses_exact_redacted_contract():
    openalgo, session = client(Response(body=analyzer_body()))

    result = openalgo.analyzer()

    assert result == {
        "_http_status": 200,
        "status": "success",
        "data": {"analyze_mode": True, "mode": "analyze"},
    }
    assert len(session.calls) == 1
    url, request = session.calls[0]
    assert url == "http://127.0.0.1:5001/api/v1/analyzer"
    assert request == {
        "json": {"apikey": "configured-secret"},
        "headers": {"Content-Type": "application/json"},
        "timeout": 4.0,
        "allow_redirects": False,
    }


@pytest.mark.parametrize(
    "base_url",
    [
        "http://127.0.0.1:5001",
        "http://127.0.0.1:5001/",
        "http://127.0.0.1:5001/api/v1",
        "http://127.0.0.1:5001/api/v1/",
    ],
)
def test_analyzer_base_url_variants_resolve_exact_api_path(base_url):
    openalgo, session = client(
        Response(body=analyzer_body()),
        base_url=base_url,
    )

    result = openalgo.analyzer()

    assert result["data"] == {"analyze_mode": True, "mode": "analyze"}
    assert openalgo.base_url == "http://127.0.0.1:5001"
    assert len(session.calls) == 1
    assert session.calls[0][0] == "http://127.0.0.1:5001/api/v1/analyzer"
    assert "/api/v1/api/v1" not in session.calls[0][0]


def test_html_200_is_explicit_auth_or_route_error():
    openalgo, _ = client(
        Response(content_type="text/html", body="<html>login</html>")
    )
    with pytest.raises(
        OracleExecutionUnavailable, match="^AUTH_OR_ROUTE_ERROR$"
    ):
        openalgo.analyzer()


def test_redirect_is_explicit_auth_redirect_error():
    openalgo, _ = client(
        Response(status_code=302, content_type="text/html", body=None)
    )
    with pytest.raises(
        OracleExecutionUnavailable, match="^AUTH_REDIRECT_ERROR$"
    ):
        openalgo.analyzer()


def test_missing_api_key_fails_before_request():
    openalgo, session = client(Response(body=analyzer_body()), api_key="")
    with pytest.raises(
        OracleExecutionUnavailable, match="^OPENALGO_CONFIG_UNAVAILABLE$"
    ):
        openalgo.analyzer()
    assert session.calls == []


def test_invalid_credentials_fail_closed_without_secret_leakage():
    secret = "never-log-this-key"
    openalgo, _ = client(
        Response(
            status_code=401,
            body={"status": "error", "message": "Invalid API key"},
        ),
        api_key=secret,
    )
    with pytest.raises(
        OracleExecutionUnavailable, match="^AUTH_OR_ROUTE_ERROR$"
    ) as captured:
        openalgo.analyzer()
    assert secret not in str(captured.value)
    assert secret not in json.dumps(captured.value.args)


def test_malformed_json_is_explicit_invalid_response():
    openalgo, _ = client(Response(malformed=True))
    with pytest.raises(
        OracleExecutionUnavailable, match="^OPENALGO_RESPONSE_INVALID$"
    ):
        openalgo.analyzer()


@pytest.mark.parametrize(
    "body",
    [
        analyzer_body(enabled=False),
        analyzer_body(mode="live"),
    ],
)
def test_analyzer_off_or_wrong_mode_blocks_autopilot(body):
    openalgo, _ = client(Response(body=body))
    autopilot = object.__new__(OraclePaperAutopilot)
    autopilot.openalgo = openalgo
    with pytest.raises(
        OracleExecutionBlocked, match="^OPENALGO_ANALYZER_REQUIRED$"
    ):
        autopilot._require_analyzer()
