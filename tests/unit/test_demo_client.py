from core.client import QihengClient


def test_demo_client_uses_synthetic_contract(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("QIHENG_BASE_URL", "demo://local")
    client = QihengClient(api_key="", base_url="demo://local")

    assert client.is_demo is True
    assert client.me()["id"] == "demo-user"
    claims = list(client.expense_claims_iterate(status="PENDING"))
    assert len(claims) >= 5
    assert claims[0]["id"].startswith("DEMO-")
    assert client.expense_claims_get(claims[0]["id"])["lines"]


def test_demo_client_records_review(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    client = QihengClient(api_key="demo", base_url="demo://local")

    result = client.expense_claims_review(
        "DEMO-0001", "FLAG", ["demo review"], violations=[]
    )

    assert result["status"] == "recorded"
    assert result["review"]["result"] == "FLAG"
