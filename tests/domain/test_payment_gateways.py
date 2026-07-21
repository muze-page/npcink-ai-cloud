from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.domain.commercial.errors import CommercialValidationError
from app.domain.commercial.payment_gateways import (
    PAYMENT_GATEWAY_CONTRACT_VERSION,
    PaymentGatewayCloseRequest,
    PaymentGatewayOrderRequest,
    PaymentGatewayRefundRequest,
    get_payment_gateway_provider,
    normalize_payment_gateway_provider,
    validate_alipay_gateway_config,
)


def _alipay_test_keys() -> tuple[object, str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_key, private_pem, public_pem


def _sign_alipay_payload(private_key: object, payload: dict[str, str]) -> str:
    canonical = "&".join(
        f"{key}={value}"
        for key, value in sorted(payload.items())
        if key not in {"sign", "sign_type"} and value
    )
    signature = private_key.sign(  # type: ignore[attr-defined]
        canonical.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def test_payment_gateway_create_order_and_refund_are_provider_normalized() -> None:
    assert normalize_payment_gateway_provider("wechat") == "wechat_pay"
    gateway = get_payment_gateway_provider("wxpay")
    order = gateway.create_order(
        PaymentGatewayOrderRequest(
            provider="wechat_pay",
            order_id="pay_gateway_order_001",
            amount=99.0,
            currency="CNY",
            subject="Small credit pack",
            metadata={"purchase_kind": "credit_pack"},
        )
    )
    refund = gateway.create_refund(
        PaymentGatewayRefundRequest(
            provider="wechat_pay",
            refund_id="ref_gateway_order_001",
            order_id="pay_gateway_order_001",
            amount=99.0,
            currency="CNY",
            reason="customer requested refund",
            metadata={},
        )
    )

    assert order.external_order_no == "pay_gateway_order_001"
    assert order.checkout_url == ""
    assert order.provider_payload["contract_version"] == PAYMENT_GATEWAY_CONTRACT_VERSION
    assert order.provider_payload["provider"] == "wechat_pay"
    assert refund.external_refund_no == "ref_gateway_order_001"
    assert refund.provider_payload["refund_status"] == "requested"


def test_alipay_gateway_verifies_payment_and_refund_callbacks() -> None:
    gateway = get_payment_gateway_provider("alipay")
    payment = gateway.verify_payment_callback(
        {
            "out_trade_no": "pay_alipay_001",
            "trade_no": "202606230000000001",
            "notify_id": "notify-alipay-payment-001",
            "total_amount": "99.00",
            "trade_status": "TRADE_SUCCESS",
            "gmt_payment": "2026-06-23 10:20:30",
        }
    )
    refund = gateway.verify_refund_callback(
        {
            "out_biz_no": "ref_alipay_001",
            "trade_no": "202606230000000001",
            "notify_id": "notify-alipay-refund-001",
            "refund_fee": "99.00",
            "refund_status": "REFUND_SUCCESS",
            "gmt_refund_pay": "2026-06-23 10:30:30",
        }
    )

    assert payment.status == "succeeded"
    assert payment.external_order_no == "pay_alipay_001"
    assert payment.provider_trade_no == "202606230000000001"
    assert payment.amount == 99.0
    assert payment.occurred_at == datetime(2026, 6, 23, 2, 20, 30, tzinfo=UTC)
    assert payment.to_payload()["contract_version"] == PAYMENT_GATEWAY_CONTRACT_VERSION
    assert refund.status == "succeeded"
    assert refund.external_refund_no == "ref_alipay_001"
    assert refund.amount == 99.0


def test_real_alipay_gateway_signs_order_and_verifies_callback() -> None:
    private_key, private_pem, public_pem = _alipay_test_keys()
    config = {
        "configured": True,
        "enabled": True,
        "app_id": "2026000000000001",
        "private_key": private_pem,
        "public_key": public_pem,
        "gateway_url": "https://openapi.alipay.com/gateway.do",
        "notify_url": "https://cloud.example.com/open/payments/alipay/notify",
        "return_url": "https://cloud.example.com/open/payments/alipay/return",
    }
    gateway = get_payment_gateway_provider("alipay", config=config)

    order = gateway.create_order(
        PaymentGatewayOrderRequest(
            provider="alipay",
            order_id="pay_real_alipay_001",
            amount=29.0,
            currency="CNY",
            subject="Npcink AI Cloud Pro 月度套餐",
            metadata={"purchase_kind": "subscription_plan"},
        )
    )
    query = parse_qs(urlsplit(order.checkout_url).query)
    assert query["app_id"] == ["2026000000000001"]
    assert query["method"] == ["alipay.trade.page.pay"]
    assert query["sign_type"] == ["RSA2"]
    assert "\"timeout_express\":\"30m\"" in query["biz_content"][0]
    assert json.loads(query["biz_content"][0])["subject"] == "Npcink AI Cloud Pro 月度套餐"
    assert order.provider_payload["gateway_mode"] == "alipay_page_pay"
    signed_params = {
        key: values[0]
        for key, values in query.items()
        if key != "sign" and values and values[0]
    }
    signed_content = "&".join(
        f"{key}={value}" for key, value in sorted(signed_params.items())
    )
    private_key.public_key().verify(  # type: ignore[attr-defined]
        base64.b64decode(query["sign"][0]),
        signed_content.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    gateway_timestamp = datetime.strptime(
        query["timestamp"][0],
        "%Y-%m-%d %H:%M:%S",
    ).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    assert abs((datetime.now(ZoneInfo("Asia/Shanghai")) - gateway_timestamp).total_seconds()) < 5

    callback = {
        "app_id": "2026000000000001",
        "out_trade_no": "pay_real_alipay_001",
        "trade_no": "202607040000000001",
        "notify_id": "notify-real-alipay-001",
        "total_amount": "29.00",
        "trade_status": "TRADE_SUCCESS",
        "gmt_payment": "2026-07-04 10:20:30",
        "sign_type": "RSA2",
    }
    callback["sign"] = _sign_alipay_payload(private_key, callback)

    payment = gateway.verify_payment_callback(callback)

    assert payment.status == "succeeded"
    assert payment.external_order_no == "pay_real_alipay_001"
    assert payment.provider_trade_no == "202607040000000001"
    assert payment.amount == 29.0
    assert payment.occurred_at == datetime(2026, 7, 4, 2, 20, 30, tzinfo=UTC)


def test_real_alipay_gateway_closes_order(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key, private_pem, public_pem = _alipay_test_keys()
    config = {
        "configured": True,
        "enabled": True,
        "app_id": "2026000000000001",
        "private_key": private_pem,
        "public_key": public_pem,
        "gateway_url": "https://openapi.alipay.com/gateway.do",
    }
    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            close_payload = {"code": "10000", "msg": "Success"}
            signed_content = json.dumps(
                close_payload,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            signature = private_key.sign(  # type: ignore[attr-defined]
                signed_content.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return {
                "alipay_trade_close_response": close_payload,
                "sign": base64.b64encode(signature).decode("ascii"),
            }

    def _post(url: str, *, data: dict[str, str], timeout: float) -> _Response:
        captured.update({"url": url, "data": data, "timeout": timeout})
        return _Response()

    monkeypatch.setattr("app.domain.commercial.payment_gateways.httpx.post", _post)
    gateway = get_payment_gateway_provider("alipay", config=config)
    result = gateway.close_order(
        PaymentGatewayCloseRequest(
            provider="alipay",
            order_id="pay_close_001",
            external_order_no="pay_close_001",
            metadata={},
        )
    )

    assert result.provider_payload["order_status"] == "closed"
    assert captured["url"] == "https://openapi.alipay.com/gateway.do"
    assert captured["timeout"] == 10.0
    assert captured["data"]["method"] == "alipay.trade.close"  # type: ignore[index]


def test_real_alipay_gateway_accepts_bare_pkcs1_private_key() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pkcs1_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    private_bare = (
        private_pkcs1_pem.replace("-----BEGIN RSA PRIVATE KEY-----", "")
        .replace("-----END RSA PRIVATE KEY-----", "")
        .strip()
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    config = {
        "configured": True,
        "enabled": True,
        "app_id": "2026000000000001",
        "private_key": private_bare,
        "public_key": public_pem,
        "gateway_url": "https://openapi.alipay.com/gateway.do",
        "notify_url": "https://cloud.example.com/open/payments/alipay/notify",
        "return_url": "https://cloud.example.com/open/payments/alipay/return",
    }
    gateway = get_payment_gateway_provider("alipay", config=config)

    order = gateway.create_order(
        PaymentGatewayOrderRequest(
            provider="alipay",
            order_id="pay_real_alipay_pkcs1_001",
            amount=29.0,
            currency="CNY",
            subject="Npcink AI Cloud Pro monthly",
            metadata={"purchase_kind": "subscription_plan"},
        )
    )

    assert parse_qs(urlsplit(order.checkout_url).query)["sign_type"] == ["RSA2"]


def test_alipay_gateway_config_accepts_distinct_platform_public_key() -> None:
    _, app_private_pem, _ = _alipay_test_keys()
    _, _, alipay_public_pem = _alipay_test_keys()

    validate_alipay_gateway_config(
        {
            "configured": True,
            "enabled": True,
            "app_id": "2026000000000001",
            "private_key": app_private_pem,
            "public_key": alipay_public_pem,
            "gateway_url": "https://openapi.alipay.com/gateway.do",
            "notify_url": "https://cloud.example.com/open/payments/alipay/notify",
            "return_url": "https://cloud.example.com/open/payments/alipay/return",
        }
    )


def test_real_alipay_gateway_reports_invalid_key_format_without_parser_details() -> None:
    config = {
        "configured": True,
        "enabled": True,
        "app_id": "2026000000000001",
        "private_key": "not-an-rsa-private-key",
        "public_key": "not-an-rsa-public-key",
        "gateway_url": "https://openapi.alipay.com/gateway.do",
        "notify_url": "https://cloud.example.com/open/payments/alipay/notify",
        "return_url": "https://cloud.example.com/open/payments/alipay/return",
    }

    with pytest.raises(CommercialValidationError) as excinfo:
        get_payment_gateway_provider("alipay", config=config).create_order(
            PaymentGatewayOrderRequest(
                provider="alipay",
                order_id="pay_real_alipay_bad_key_001",
                amount=29.0,
                currency="CNY",
                subject="Npcink AI Cloud Pro monthly",
                metadata={},
            )
        )

    assert excinfo.value.error_code == "service.alipay_private_key_format_invalid"
    assert "ASN.1" not in str(excinfo.value)
    assert "Could not deserialize" not in str(excinfo.value)


def test_wechat_gateway_verifies_cent_amount_callbacks() -> None:
    gateway = get_payment_gateway_provider("wechat_pay")
    payment = gateway.verify_payment_callback(
        {
            "out_trade_no": "pay_wechat_001",
            "transaction_id": "420000000020260623000001",
            "event_id": "notify-wechat-payment-001",
            "amount": {"total": 9900},
            "trade_state": "SUCCESS",
            "success_time": "2026-06-23T10:20:30+08:00",
        }
    )
    refund = gateway.verify_refund_callback(
        {
            "out_refund_no": "ref_wechat_001",
            "refund_id": "503000000020260623000001",
            "event_id": "notify-wechat-refund-001",
            "amount": {"refund": 9900},
            "refund_status": "SUCCESS",
            "success_time": "2026-06-23T10:30:30+08:00",
        }
    )

    assert payment.status == "succeeded"
    assert payment.amount == 99.0
    assert payment.provider_trade_no == "420000000020260623000001"
    assert refund.status == "succeeded"
    assert refund.amount == 99.0
    assert refund.provider_refund_no == "503000000020260623000001"


def test_gateway_callback_requires_external_order_or_refund_number() -> None:
    gateway = get_payment_gateway_provider("alipay")
    with pytest.raises(CommercialValidationError) as payment_error:
        gateway.verify_payment_callback({"trade_status": "TRADE_SUCCESS"})
    with pytest.raises(CommercialValidationError) as refund_error:
        gateway.verify_refund_callback({"refund_status": "REFUND_SUCCESS"})

    assert payment_error.value.error_code == "service.payment_callback_order_missing"
    assert refund_error.value.error_code == "service.payment_refund_callback_missing"
