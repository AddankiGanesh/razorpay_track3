from functools import lru_cache

import razorpay

from app.config import get_settings


@lru_cache
def get_razorpay_client() -> razorpay.Client:
    settings = get_settings()
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
