"""Minimal Razorpay Standard Checkout API and demonstration page."""

from html import escape

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.checkout import (
    CheckoutOrderCreateIn,
    CheckoutOrderOut,
    CheckoutVerificationIn,
    CheckoutVerificationOut,
)
from app.services.checkout_service import (
    CheckoutOrderCreationError,
    CheckoutOrderStateError,
    UnknownCheckoutOrderError,
    create_checkout_order,
    find_checkout_payment,
    record_verified_checkout_payment,
)
from app.services.payment_gateway import PaymentGateway, RazorpayPaymentGateway
from app.services.razorpay_client import CheckoutSignatureError, verify_checkout_payment_signature

router = APIRouter(prefix="/payments", tags=["payments"])


def get_payment_gateway() -> PaymentGateway:
    return RazorpayPaymentGateway()


@router.post("/checkout/orders", response_model=CheckoutOrderOut, status_code=status.HTTP_201_CREATED)
def create_standard_checkout_order(
    payload: CheckoutOrderCreateIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    gateway: PaymentGateway = Depends(get_payment_gateway),
) -> CheckoutOrderOut:
    try:
        payment = create_checkout_order(db, gateway, amount_rupees=payload.amount_rupees)
        db.commit()
    except CheckoutOrderCreationError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to create Razorpay order") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return CheckoutOrderOut(
        order_id=payment.razorpay_order_id or "",
        amount=payment.amount,
        currency=payment.currency,
        key_id=settings.RAZORPAY_KEY_ID,
    )


@router.post("/checkout/verify", response_model=CheckoutVerificationOut)
def verify_standard_checkout_payment(
    payload: CheckoutVerificationIn,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CheckoutVerificationOut:
    try:
        # Look up our order first; never use a browser-supplied order as the authority.
        find_checkout_payment(db, razorpay_order_id=payload.razorpay_order_id)
        verify_checkout_payment_signature(
            order_id=payload.razorpay_order_id,
            payment_id=payload.razorpay_payment_id,
            signature=payload.razorpay_signature,
            key_secret=settings.RAZORPAY_KEY_SECRET,
        )
        record_verified_checkout_payment(
            db,
            order_id=payload.razorpay_order_id,
            payment_id=payload.razorpay_payment_id,
        )
        db.commit()
    except UnknownCheckoutOrderError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown checkout order") from exc
    except CheckoutSignatureError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payment signature") from exc
    except CheckoutOrderStateError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return CheckoutVerificationOut(
        status="verified_pending_webhook",
        detail="Signature verified; awaiting Razorpay webhook for payment state.",
    )


@router.get("/checkout", response_class=HTMLResponse, include_in_schema=False)
def standard_checkout_page(settings: Settings = Depends(get_settings)) -> HTMLResponse:
    key_id = escape(settings.RAZORPAY_KEY_ID, quote=True)
    return HTMLResponse(f"""<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>Razorpay Test Checkout</title><script src=\"https://checkout.razorpay.com/v1/checkout.js\"></script></head>
<body><main><h1>Razorpay Test Checkout</h1><label>Amount (INR) <input id=\"amount\" type=\"number\" min=\"1\" step=\"0.01\" value=\"100.00\"></label>
<button id=\"pay\" type=\"button\">Pay with Razorpay</button><pre id=\"result\" aria-live=\"polite\"></pre></main>
<script>
const result = document.getElementById('result');
document.getElementById('pay').addEventListener('click', async () => {{
  result.textContent = 'Creating order...';
  const response = await fetch('/api/v1/payments/checkout/orders', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{amount_rupees:document.getElementById('amount').value}})}});
  const order = await response.json();
  if (!response.ok) {{ result.textContent = order.detail || 'Unable to create order'; return; }}
  const checkout = new Razorpay({{key:order.key_id || '{key_id}', amount:order.amount, currency:order.currency, order_id:order.order_id, name:'Revenue Recovery', description:'Test checkout', handler:async (payment) => {{
    const verify = await fetch('/api/v1/payments/checkout/verify', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(payment)}});
    const body = await verify.json(); result.textContent = body.detail || JSON.stringify(body);
  }}}});
  checkout.on('payment.failed', (event) => {{ result.textContent = 'Payment failed. Razorpay webhook will record the failure.'; }});
  checkout.open();
}});
</script></body></html>""")
