"""REST API + dashboard.  Run: python -m scripts.serve  (docs at /docs)."""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import OFFER_COST, ROOT, SAVE_RATE, VALUE_MONTHS
from .service import get

YesNo = Literal["Yes", "No"]


class Customer(BaseModel):
    """One customer in the IBM Telco format (the same fields a CRM export would have)."""
    customerID: str = Field("new", max_length=40)
    gender: Literal["Female", "Male"] = "Female"
    SeniorCitizen: Literal[0, 1] = 0
    Partner: YesNo = "No"
    Dependents: YesNo = "No"
    tenure: int = Field(1, ge=0, le=120)
    PhoneService: YesNo = "Yes"
    MultipleLines: Literal["Yes", "No", "No phone service"] = "No"
    InternetService: Literal["DSL", "Fiber optic", "No"] = "Fiber optic"
    OnlineSecurity: Literal["Yes", "No", "No internet service"] = "No"
    OnlineBackup: Literal["Yes", "No", "No internet service"] = "No"
    DeviceProtection: Literal["Yes", "No", "No internet service"] = "No"
    TechSupport: Literal["Yes", "No", "No internet service"] = "No"
    StreamingTV: Literal["Yes", "No", "No internet service"] = "No"
    StreamingMovies: Literal["Yes", "No", "No internet service"] = "No"
    Contract: Literal["Month-to-month", "One year", "Two year"] = "Month-to-month"
    PaperlessBilling: YesNo = "Yes"
    PaymentMethod: Literal["Electronic check", "Mailed check", "Bank transfer (automatic)", "Credit card (automatic)"] = "Electronic check"
    MonthlyCharges: float = Field(70.0, ge=0, le=1000)
    TotalCharges: float | None = Field(None, ge=0, le=100000)


class Campaign(BaseModel):
    offer_cost: float = Field(OFFER_COST, ge=0, le=10000)
    save_rate: float = Field(SAVE_RATE, gt=0, le=1)
    value_months: int = Field(VALUE_MONTHS, ge=1, le=60)


class ScoreRequest(BaseModel):
    customer: Customer
    campaign: Campaign = Campaign()


class RateLimit:
    """Small in-memory sliding window per client (single process demo)."""

    def __init__(self, app, per_min: int):
        self.app, self.per_min, self.hits = app, per_min, defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/"):
            client = dict(scope.get("headers", [])).get(b"x-forwarded-for", b"").decode().split(",")[0].strip() or (
                scope.get("client") or ("?",))[0]
            q, now = self.hits[client], time.monotonic()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_min:
                resp = JSONResponse({"detail": "Too many requests - wait a minute."}, status_code=429)
                return await resp(scope, receive, send)
            q.append(now)
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(_):
    get()
    yield


api = FastAPI(title="Wafa — churn prediction and retention", version="1.0.0", lifespan=lifespan,
              description="Scores telecom customers for churn risk, explains each score and recommends whether a "
                          "retention offer is worth sending.")
api.add_middleware(GZipMiddleware, minimum_size=1000)
api.add_middleware(RateLimit, per_min=int(os.getenv("WAFA_REQUESTS_PER_MIN", "240")))


@api.middleware("http")
async def headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
        resp.headers.setdefault("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' "
                                "'unsafe-inline'; script-src 'self'; font-src 'self'; frame-ancestors 'self' https://huggingface.co https://*.hf.space")
    return resp


@api.get("/health")
def health():
    m = get().metrics
    return {"status": "ok", "model": "xgboost", "test_auc": round(m["test"]["xgboost"]["auc"], 4)}


@api.get("/api/metrics")
def metrics():
    return get().metrics


@api.get("/api/customers")
def customers(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), min_probability: float = Query(0, ge=0, le=1)):
    rows = [c for c in get().customers if c["p"] >= min_probability]
    return {"total": len(rows), "items": [{k: v for k, v in c.items() if k != "churned"} for c in rows[offset:offset + limit]]}


@api.get("/api/customers/{customer_id}")
def customer(customer_id: str):
    c = get().by_id.get(customer_id)
    if c is None:
        raise HTTPException(404, "customer not found")
    return {k: v for k, v in c.items() if k != "churned"}


@api.post("/api/score")
def score(body: ScoreRequest):
    raw = body.customer.model_dump()
    raw["SeniorCitizen"] = str(raw["SeniorCitizen"])
    raw["tenure"] = str(raw["tenure"])
    raw["MonthlyCharges"] = str(raw["MonthlyCharges"])
    tc = raw["TotalCharges"]
    raw["TotalCharges"] = "" if tc is None and body.customer.tenure == 0 else str(
        tc if tc is not None else body.customer.MonthlyCharges * body.customer.tenure)
    c = body.campaign
    return get().score(raw, c.offer_cost, c.save_rate, c.value_months)


WEB = ROOT / "web"
if WEB.exists():
    api.mount("/", StaticFiles(directory=WEB, html=True), name="web")
