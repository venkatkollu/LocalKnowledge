import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import Authenticator
from app.citations import validate_answer
from app.config import Settings


def request(host="127.0.0.1:8000", origin=None, peer="127.0.0.1"):
    headers = [(b"host", host.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "POST", "scheme": "http", "path": "/chat", "query_string": b"", "headers": headers, "client": (peer, 1000), "server": ("127.0.0.1", 8000)})


def test_local_auth_blocks_remote_peers_origins_and_dns_rebinding():
    auth = Authenticator(Settings())
    assert auth.authenticate(request()).admin
    for item in (request(peer="192.0.2.1"), request(origin="https://attacker.invalid"), request(host="attacker.invalid", origin="http://attacker.invalid")):
        with pytest.raises(HTTPException) as exc:
            auth.authenticate(item)
        assert exc.value.status_code == 403


def test_numbers_negation_missing_citations_and_weak_evidence():
    evidence = [{"raw_content": "The cache expiry is 300 seconds. Redis caches responses."}]
    for answer in ("The cache expiry is 900 seconds [1].", "Redis never caches responses [1].", "Redis caches responses.", "The lunar budget is a trillion dollars [1]."):
        assert not validate_answer(answer, evidence)["valid"]
    assert validate_answer("The cache expiry is 300 seconds [1].", evidence)["valid"]
