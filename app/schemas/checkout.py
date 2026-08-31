"""Request and response models for Razorpay Standard Checkout."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CheckoutOrderCreateIn(BaseModel):
    # Amounts enter this API in rupees; Razorpay receives paise.
    amount_rupees: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class CheckoutOrderOut(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str


class CheckoutVerificationIn(BaseModel):
    razorpay_order_id: str = Field(min_length=1, max_length=64)
    razorpay_payment_id: str = Field(min_length=1, max_length=64)
    razorpay_signature: str = Field(min_length=1, max_length=128)


class CheckoutVerificationOut(BaseModel):
    status: str
    detail: str
    model_config = ConfigDict(from_attributes=True)
