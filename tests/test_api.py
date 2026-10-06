import pytest
from fastapi.testclient import TestClient

from wafa.api import api
from wafa.config import WEB_DATA

pytestmark = pytest.mark.skipif(not (WEB_DATA / "customers.json").exists(), reason="run python -m scripts.build first")


@pytest.fixture(scope="module")
def client():
    with TestClient(api) as c:
        yield c


RISKY = {"tenure": 1, "Contract": "Month-to-month", "InternetService": "Fiber optic", "PaymentMethod": "Electronic check",
         "MonthlyCharges": 95.0, "OnlineSecurity": "No", "TechSupport": "No", "PaperlessBilling": "Yes"}
SAFE = {"tenure": 70, "Contract": "Two year", "InternetService": "DSL", "PaymentMethod": "Credit card (automatic)",
        "MonthlyCharges": 60.0, "OnlineSecurity": "Yes", "TechSupport": "Yes", "Partner": "Yes", "PaperlessBilling": "No"}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_score_orders_customers_sensibly(client):
    hi = client.post("/api/score", json={"customer": RISKY}).json()
    lo = client.post("/api/score", json={"customer": SAFE}).json()
    assert hi["churn_probability"] > 0.6 > 0.1 > lo["churn_probability"]
    assert hi["risk_band"] == "high" and lo["risk_band"] == "low"
    assert any(r["text"] == "Month-to-month contract" for r in hi["risk"]) and hi["actions"]
    assert not any("$0 above" in r["text"] for r in lo["risk"])
    assert hi["offer"]["recommend"] and not lo["offer"]["recommend"]


def test_campaign_assumptions_change_the_decision(client):
    cheap = client.post("/api/score", json={"customer": RISKY, "campaign": {"offer_cost": 5}}).json()
    costly = client.post("/api/score", json={"customer": RISKY, "campaign": {"offer_cost": 5000}}).json()
    assert cheap["offer"]["recommend"] and not costly["offer"]["recommend"]


def test_validation(client):
    assert client.post("/api/score", json={"customer": {"Contract": "Weekly"}}).status_code == 422
    assert client.post("/api/score", json={"customer": {"tenure": -1}}).status_code == 422
    assert client.post("/api/score", json={"customer": RISKY, "campaign": {"save_rate": 2}}).status_code == 422


def test_customers_list_hides_outcome(client):
    r = client.get("/api/customers?limit=5").json()
    assert r["total"] == 1409 and len(r["items"]) == 5
    assert "churned" not in r["items"][0]
    ps = [c["p"] for c in r["items"]]
    assert ps == sorted(ps, reverse=True)
    assert client.get(f"/api/customers/{r['items'][0]['id']}").status_code == 200
    assert client.get("/api/customers/nope").status_code == 404


def test_dashboard_served_with_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "default-src 'self'" in r.headers["content-security-policy"]
