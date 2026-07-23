"""
ShortGen — 결제 뼈대 (Stripe 구독). 환경변수 키 오면 활성, 없으면 비활성.
⚠️ 사용자 Stripe 계정·키가 있어야 실동작(테스트 불가 지점). 통합 지점은 완성.

필요 env:
  STRIPE_SECRET_KEY   = sk_...        (Stripe 대시보드)
  STRIPE_PRICE_ID     = price_...     (Pro 구독 상품 가격)
  STRIPE_WEBHOOK_SECRET = whsec_...   (웹훅 서명검증)
  PUBLIC_URL          = https://...   (성공/취소 리다이렉트 베이스)

붙일 때: pip install stripe, main.py 에서 라우터 포함 + 생성 게이트를 has_active_sub()로.
"""
import os

SECRET = os.environ.get("STRIPE_SECRET_KEY")
PRICE = os.environ.get("STRIPE_PRICE_ID")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8080")

ENABLED = bool(SECRET and PRICE)

# 구독자 저장 (MVP=메모리; 배포 시 DB/KV로 교체). email -> active bool
SUBSCRIBERS = set()


def _stripe():
    import stripe                      # lazy: 키 없으면 import 안 함
    stripe.api_key = SECRET
    return stripe


def create_checkout(email: str) -> str:
    """Pro 구독 체크아웃 세션 URL 반환."""
    if not ENABLED:
        raise RuntimeError("결제 비활성 (STRIPE_SECRET_KEY/PRICE_ID 없음)")
    s = _stripe()
    sess = s.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": PRICE, "quantity": 1}],
        customer_email=email or None,
        success_url=PUBLIC_URL + "/?paid=1",
        cancel_url=PUBLIC_URL + "/?canceled=1",
    )
    return sess.url


def handle_webhook(payload: bytes, sig_header: str = "") -> dict:
    """Stripe 웹훅: 구독 완료/취소 반영."""
    if not ENABLED:
        return {"ok": False, "reason": "disabled"}
    s = _stripe()
    if WEBHOOK_SECRET:
        event = s.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    else:
        import json
        event = json.loads(payload)
    t = event["type"]
    obj = event["data"]["object"]
    if t == "checkout.session.completed":
        SUBSCRIBERS.add((obj.get("customer_email") or "").lower())
    elif t in ("customer.subscription.deleted",):
        # 실제로는 customer->email 매핑 필요. MVP 표식.
        pass
    return {"ok": True, "type": t}


def has_active_sub(email: str) -> bool:
    if not ENABLED:
        return True                    # 결제 붙기 전엔 전부 허용(데모)
    return (email or "").lower() in SUBSCRIBERS
