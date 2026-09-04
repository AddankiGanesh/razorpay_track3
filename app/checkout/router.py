"""Checkout.js demo — create real Razorpay orders for pitch video."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.config import PROJECT_ROOT, get_settings
from app.services.razorpay_client import get_razorpay_client

router = APIRouter(tags=["checkout"])
CHECKOUT_HTML = PROJECT_ROOT / "app" / "ui" / "checkout.html"


class CreateOrderBody(BaseModel):
    amount_paise: int = Field(default=49900, ge=100, le=50000000)
    email: str = "ganeshsuraj29@gmail.com"


@router.get("/checkout", response_class=HTMLResponse)
def checkout_page() -> str:
    return CHECKOUT_HTML.read_text(encoding="utf-8")


@router.post("/checkout/create-order")
def create_order(body: CreateOrderBody) -> dict[str, Any]:
    settings = get_settings()
    client = get_razorpay_client()
    try:
        order = client.order.create(
            {
                "amount": body.amount_paise,
                "currency": "INR",
                "payment_capture": 1,
                "notes": {"source": "revrecover_checkout_demo", "email": body.email},
            }
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "order_id": order["id"],
        "amount": order["amount"],
        "currency": order.get("currency", "INR"),
        "key_id": settings.razorpay_key_id,
        "email": body.email,
    }
