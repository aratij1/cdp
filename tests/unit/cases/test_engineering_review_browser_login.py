"""Browser login regression: preserve same-origin form metadata and CSRF rejection."""
from fastapi.testclient import TestClient

from evaluation.engineering_review_app import create_app


def test_browser_same_origin_login_keeps_cookie_and_redirects():
    client=TestClient(create_app("synthetic-reviewer","synthetic-private-token"),base_url="http://127.0.0.1:8766")
    page=client.get("/")
    assert page.headers["referrer-policy"]=="same-origin"
    assert page.headers["cache-control"]=="no-store"
    result=client.post("/login",headers={"Origin":"http://127.0.0.1:8766"},
                       data={"token":"synthetic-private-token"},follow_redirects=False)
    assert result.status_code==303 and result.headers["location"]=="/fields"
    assert "engineering_review_session" in result.cookies


def test_cross_origin_null_origin_and_wrong_code_still_fail():
    client=TestClient(create_app("synthetic-reviewer","synthetic-private-token"),base_url="http://127.0.0.1:8766")
    for origin in ["null","https://untrusted.invalid","http://localhost:8766"]:
        result=client.post("/login",headers={"Origin":origin},data={"token":"synthetic-private-token"},follow_redirects=False)
        assert result.status_code==403
    assert client.post("/login",headers={"Origin":"http://127.0.0.1:8766"},data={"token":"wrong"}).status_code==403
