from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.domain.commercial.errors import CommercialValidationError

PAYMENT_GATEWAY_CONTRACT_VERSION = "payment-gateway-contract-v1"
SUPPORTED_PAYMENT_GATEWAY_PROVIDERS = ("alipay", "wechat_pay", "manual")
ALIPAY_GATEWAY_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class PaymentGatewayOrderRequest:
    provider: str
    order_id: str
    amount: float
    currency: str
    subject: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class PaymentGatewayOrderResult:
    provider: str
    external_order_no: str
    checkout_url: str
    provider_payload: dict[str, object]


@dataclass(frozen=True)
class PaymentGatewayCloseRequest:
    provider: str
    order_id: str
    external_order_no: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class PaymentGatewayCloseResult:
    provider: str
    external_order_no: str
    provider_payload: dict[str, object]


@dataclass(frozen=True)
class PaymentGatewayRefundRequest:
    provider: str
    refund_id: str
    order_id: str
    amount: float
    currency: str
    reason: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class PaymentGatewayRefundResult:
    provider: str
    external_refund_no: str
    provider_payload: dict[str, object]


@dataclass(frozen=True)
class PaymentGatewayCallbackResult:
    provider: str
    external_order_no: str
    provider_trade_no: str
    provider_event_id: str
    amount: float | None
    status: str
    occurred_at: datetime | None
    raw_event: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {
            "contract_version": PAYMENT_GATEWAY_CONTRACT_VERSION,
            "provider": self.provider,
            "external_order_no": self.external_order_no,
            "provider_trade_no": self.provider_trade_no,
            "provider_event_id": self.provider_event_id,
            "amount": self.amount,
            "status": self.status,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else "",
            "raw_event": self.raw_event,
        }


@dataclass(frozen=True)
class PaymentGatewayRefundCallbackResult:
    provider: str
    external_refund_no: str
    provider_refund_no: str
    provider_event_id: str
    amount: float | None
    status: str
    occurred_at: datetime | None
    raw_event: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return {
            "contract_version": PAYMENT_GATEWAY_CONTRACT_VERSION,
            "provider": self.provider,
            "external_refund_no": self.external_refund_no,
            "provider_refund_no": self.provider_refund_no,
            "provider_event_id": self.provider_event_id,
            "amount": self.amount,
            "status": self.status,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else "",
            "raw_event": self.raw_event,
        }


class PaymentGatewayProvider(Protocol):
    provider: str

    def create_order(self, request: PaymentGatewayOrderRequest) -> PaymentGatewayOrderResult:
        ...

    def create_refund(self, request: PaymentGatewayRefundRequest) -> PaymentGatewayRefundResult:
        ...

    def close_order(self, request: PaymentGatewayCloseRequest) -> PaymentGatewayCloseResult:
        ...

    def verify_payment_callback(
        self,
        payload: dict[str, object],
    ) -> PaymentGatewayCallbackResult:
        ...

    def verify_refund_callback(
        self,
        payload: dict[str, object],
    ) -> PaymentGatewayRefundCallbackResult:
        ...


def normalize_payment_gateway_provider(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized in {"wechat", "wxpay"}:
        normalized = "wechat_pay"
    if normalized not in SUPPORTED_PAYMENT_GATEWAY_PROVIDERS:
        raise CommercialValidationError(
            "service.payment_provider_unsupported",
            "payment provider must be alipay, wechat_pay, or manual",
        )
    return normalized


def get_payment_gateway_provider(
    provider: str,
    *,
    config: Mapping[str, object] | None = None,
) -> PaymentGatewayProvider:
    normalized = normalize_payment_gateway_provider(provider)
    if normalized == "alipay":
        return AlipayPaymentGatewayProvider(config=config)
    if normalized == "wechat_pay":
        return WeChatPayPaymentGatewayProvider()
    return ManualPaymentGatewayProvider()


class SimulatedPaymentGatewayProvider:
    provider = "manual"
    checkout_mode = "simulated"

    def create_order(self, request: PaymentGatewayOrderRequest) -> PaymentGatewayOrderResult:
        self._assert_provider(request.provider)
        return PaymentGatewayOrderResult(
            provider=self.provider,
            external_order_no=request.order_id,
            checkout_url="",
            provider_payload={
                "contract_version": PAYMENT_GATEWAY_CONTRACT_VERSION,
                "provider": self.provider,
                "gateway_mode": self.checkout_mode,
                "order_status": "created",
            },
        )

    def create_refund(self, request: PaymentGatewayRefundRequest) -> PaymentGatewayRefundResult:
        self._assert_provider(request.provider)
        return PaymentGatewayRefundResult(
            provider=self.provider,
            external_refund_no=request.refund_id,
            provider_payload={
                "contract_version": PAYMENT_GATEWAY_CONTRACT_VERSION,
                "provider": self.provider,
                "gateway_mode": self.checkout_mode,
                "refund_status": "requested",
            },
        )

    def close_order(self, request: PaymentGatewayCloseRequest) -> PaymentGatewayCloseResult:
        self._assert_provider(request.provider)
        return PaymentGatewayCloseResult(
            provider=self.provider,
            external_order_no=request.external_order_no or request.order_id,
            provider_payload={
                "contract_version": PAYMENT_GATEWAY_CONTRACT_VERSION,
                "provider": self.provider,
                "gateway_mode": self.checkout_mode,
                "order_status": "closed",
            },
        )

    def verify_payment_callback(
        self,
        payload: dict[str, object],
    ) -> PaymentGatewayCallbackResult:
        external_order_no = _first_text(payload, "out_trade_no", "order_id", "external_order_no")
        provider_trade_no = _first_text(
            payload,
            "trade_no",
            "transaction_id",
            "provider_trade_no",
        )
        if not external_order_no:
            raise CommercialValidationError(
                "service.payment_callback_order_missing",
                "payment callback is missing the external order number",
            )
        return PaymentGatewayCallbackResult(
            provider=self.provider,
            external_order_no=external_order_no,
            provider_trade_no=provider_trade_no,
            provider_event_id=_first_text(payload, "notify_id", "event_id", "provider_event_id"),
            amount=_first_float(payload, "total_amount", "amount", "total"),
            status=self._payment_callback_status(payload),
            occurred_at=_first_datetime(payload, "gmt_payment", "success_time", "paid_at"),
            raw_event=dict(payload),
        )

    def verify_refund_callback(
        self,
        payload: dict[str, object],
    ) -> PaymentGatewayRefundCallbackResult:
        external_refund_no = _first_text(
            payload,
            "out_biz_no",
            "out_refund_no",
            "refund_id",
            "external_refund_no",
        )
        provider_refund_no = _first_text(
            payload,
            "trade_no",
            "refund_id",
            "provider_refund_no",
        )
        if not external_refund_no:
            raise CommercialValidationError(
                "service.payment_refund_callback_missing",
                "refund callback is missing the external refund number",
            )
        return PaymentGatewayRefundCallbackResult(
            provider=self.provider,
            external_refund_no=external_refund_no,
            provider_refund_no=provider_refund_no,
            provider_event_id=_first_text(payload, "notify_id", "event_id", "provider_event_id"),
            amount=_first_float(payload, "refund_fee", "amount", "refund"),
            status=self._refund_callback_status(payload),
            occurred_at=_first_datetime(payload, "gmt_refund_pay", "success_time", "succeeded_at"),
            raw_event=dict(payload),
        )

    def _assert_provider(self, provider: str) -> None:
        if normalize_payment_gateway_provider(provider) != self.provider:
            raise CommercialValidationError(
                "service.payment_provider_mismatch",
                "payment provider does not match the gateway implementation",
            )

    def _payment_callback_status(self, payload: dict[str, object]) -> str:
        status = _first_text(payload, "trade_status", "trade_state", "status").upper()
        if status in {"TRADE_SUCCESS", "TRADE_FINISHED", "SUCCESS", "PAID"}:
            return "succeeded"
        return "ignored"

    def _refund_callback_status(self, payload: dict[str, object]) -> str:
        status = _first_text(payload, "refund_status", "refund_state", "status").upper()
        if status in {"REFUND_SUCCESS", "SUCCESS", "SUCCEEDED"}:
            return "succeeded"
        return "ignored"


class AlipayPaymentGatewayProvider(SimulatedPaymentGatewayProvider):
    provider = "alipay"

    def __init__(self, *, config: Mapping[str, object] | None = None) -> None:
        self.config = dict(config or {})

    def create_order(self, request: PaymentGatewayOrderRequest) -> PaymentGatewayOrderResult:
        if not self._real_gateway_enabled():
            return super().create_order(request)
        self._assert_provider(request.provider)
        config = self._require_config()
        timestamp = datetime.now(ALIPAY_GATEWAY_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
        amount = _format_cny_amount(request.amount)
        biz_content = {
            "out_trade_no": request.order_id,
            "total_amount": amount,
            "subject": request.subject[:256],
            "product_code": _config_text(config, "payment_product_code")
            or "FAST_INSTANT_TRADE_PAY",
            "timeout_express": "30m",
        }
        params: dict[str, str] = {
            "app_id": _config_text(config, "app_id"),
            "method": "alipay.trade.page.pay",
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": timestamp,
            "version": "1.0",
            "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
        }
        if _config_text(config, "notify_url"):
            params["notify_url"] = _config_text(config, "notify_url")
        if _config_text(config, "return_url"):
            params["return_url"] = _config_text(config, "return_url")
        params["sign"] = self._sign_params(params)
        checkout_url = f"{_config_text(config, 'gateway_url')}?{urlencode(params)}"
        return PaymentGatewayOrderResult(
            provider=self.provider,
            external_order_no=request.order_id,
            checkout_url=checkout_url,
            provider_payload={
                "contract_version": PAYMENT_GATEWAY_CONTRACT_VERSION,
                "provider": self.provider,
                "gateway_mode": "alipay_page_pay",
                "order_status": "created",
                "method": "alipay.trade.page.pay",
                "sign_type": "RSA2",
                "timeout_express": "30m",
            },
        )

    def verify_payment_callback(
        self,
        payload: dict[str, object],
    ) -> PaymentGatewayCallbackResult:
        if not self._real_gateway_enabled():
            return super().verify_payment_callback(payload)
        self._verify_callback_signature(payload)
        return super().verify_payment_callback(payload)

    def close_order(self, request: PaymentGatewayCloseRequest) -> PaymentGatewayCloseResult:
        if not self._real_gateway_enabled():
            return super().close_order(request)
        self._assert_provider(request.provider)
        config = self._require_config()
        timestamp = datetime.now(ALIPAY_GATEWAY_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
        biz_content = {
            "out_trade_no": request.external_order_no or request.order_id,
        }
        params: dict[str, str] = {
            "app_id": _config_text(config, "app_id"),
            "method": "alipay.trade.close",
            "format": "JSON",
            "charset": "utf-8",
            "sign_type": "RSA2",
            "timestamp": timestamp,
            "version": "1.0",
            "biz_content": json.dumps(biz_content, ensure_ascii=False, separators=(",", ":")),
        }
        params["sign"] = self._sign_params(params)
        try:
            response = httpx.post(
                _config_text(config, "gateway_url"),
                data=params,
                timeout=10.0,
            )
            response.raise_for_status()
            response_payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise CommercialValidationError(
                "service.alipay_order_close_failed",
                "Alipay did not confirm that the unpaid order was closed",
            ) from error
        if not isinstance(response_payload, dict):
            raise CommercialValidationError(
                "service.alipay_order_close_failed",
                "Alipay returned an invalid order close response",
            )
        close_payload = response_payload.get("alipay_trade_close_response", {})
        if not isinstance(close_payload, dict) or str(close_payload.get("code") or "") != "10000":
            raise CommercialValidationError(
                "service.alipay_order_close_failed",
                "Alipay did not confirm that the unpaid order was closed",
            )
        self._verify_response_signature(
            close_payload,
            str(response_payload.get("sign") or ""),
        )
        return PaymentGatewayCloseResult(
            provider=self.provider,
            external_order_no=request.external_order_no or request.order_id,
            provider_payload={
                "contract_version": PAYMENT_GATEWAY_CONTRACT_VERSION,
                "provider": self.provider,
                "gateway_mode": "alipay_trade_close",
                "order_status": "closed",
                "code": "10000",
            },
        )

    def verify_refund_callback(
        self,
        payload: dict[str, object],
    ) -> PaymentGatewayRefundCallbackResult:
        if not self._real_gateway_enabled():
            return super().verify_refund_callback(payload)
        self._verify_callback_signature(payload)
        return super().verify_refund_callback(payload)

    def _real_gateway_enabled(self) -> bool:
        config = self.config
        if not bool(config.get("configured")) or not bool(config.get("enabled", True)):
            return False
        return bool(
            _config_text(config, "app_id")
            and _config_text(config, "private_key")
            and _config_text(config, "public_key")
            and _config_text(config, "gateway_url")
        )

    def _require_config(self) -> dict[str, object]:
        if not self._real_gateway_enabled():
            raise CommercialValidationError(
                "service.alipay_gateway_not_configured",
                "Alipay payment gateway settings are not configured",
            )
        return self.config

    def _sign_params(self, params: Mapping[str, object]) -> str:
        config = self._require_config()
        private_key = _load_alipay_private_key(_config_text(config, "private_key"))
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise CommercialValidationError(
                "service.alipay_private_key_invalid",
                "Alipay private key must be an RSA private key",
            )
        signature = private_key.sign(
            _canonicalize_alipay_request_params(params).encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("ascii")

    def _verify_callback_signature(self, payload: dict[str, object]) -> None:
        config = self._require_config()
        app_id = _first_text(payload, "app_id")
        if app_id and app_id != _config_text(config, "app_id"):
            raise CommercialValidationError(
                "service.payment_callback_app_mismatch",
                "Alipay callback app_id does not match the configured app",
            )
        signature = _first_text(payload, "sign")
        if not signature:
            raise CommercialValidationError(
                "service.payment_callback_signature_missing",
                "Alipay callback is missing its signature",
            )
        public_key = _load_alipay_public_key(_config_text(config, "public_key"))
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise CommercialValidationError(
                "service.alipay_public_key_invalid",
                "Alipay public key must be an RSA public key",
            )
        try:
            public_key.verify(
                base64.b64decode(signature),
                _canonicalize_alipay_callback_params(payload).encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError) as error:
            raise CommercialValidationError(
                "service.payment_callback_signature_invalid",
                "Alipay callback signature is invalid",
            ) from error

    def _verify_response_signature(
        self,
        response_payload: dict[str, object],
        signature: str,
    ) -> None:
        if not signature:
            raise CommercialValidationError(
                "service.alipay_response_signature_missing",
                "Alipay response is missing its signature",
            )
        config = self._require_config()
        public_key = _load_alipay_public_key(_config_text(config, "public_key"))
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise CommercialValidationError(
                "service.alipay_public_key_invalid",
                "Alipay public key must be an RSA public key",
            )
        signed_content = json.dumps(
            response_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            public_key.verify(
                base64.b64decode(signature),
                signed_content.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError) as error:
            raise CommercialValidationError(
                "service.alipay_response_signature_invalid",
                "Alipay response signature is invalid",
            ) from error


def validate_alipay_gateway_config(config: Mapping[str, object]) -> None:
    normalized = dict(config or {})
    required_keys = [
        "app_id",
        "gateway_url",
        "notify_url",
        "return_url",
        "private_key",
        "public_key",
    ]
    if any(not _config_text(normalized, key) for key in required_keys):
        raise CommercialValidationError(
            "service.alipay_gateway_not_configured",
            "Alipay payment gateway settings are not configured",
        )
    private_key = _load_alipay_private_key(_config_text(normalized, "private_key"))
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise CommercialValidationError(
            "service.alipay_private_key_invalid",
            "Alipay private key must be an RSA private key",
        )
    public_key = _load_alipay_public_key(_config_text(normalized, "public_key"))
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise CommercialValidationError(
            "service.alipay_public_key_invalid",
            "Alipay public key must be an RSA public key",
        )
    probe = b"npcink-ai-cloud-alipay-config-check"
    private_key.sign(probe, padding.PKCS1v15(), hashes.SHA256())


class WeChatPayPaymentGatewayProvider(SimulatedPaymentGatewayProvider):
    provider = "wechat_pay"

    def verify_payment_callback(
        self,
        payload: dict[str, object],
    ) -> PaymentGatewayCallbackResult:
        normalized = dict(payload)
        amount = payload.get("amount")
        if isinstance(amount, dict) and "total" in amount:
            normalized["amount"] = round(_coerce_float(amount.get("total")) / 100, 6)
        return super().verify_payment_callback(normalized)

    def verify_refund_callback(
        self,
        payload: dict[str, object],
    ) -> PaymentGatewayRefundCallbackResult:
        normalized = dict(payload)
        amount = payload.get("amount")
        if isinstance(amount, dict) and "refund" in amount:
            normalized["amount"] = round(_coerce_float(amount.get("refund")) / 100, 6)
        return super().verify_refund_callback(normalized)


class ManualPaymentGatewayProvider(SimulatedPaymentGatewayProvider):
    provider = "manual"


def _first_text(payload: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _config_text(config: Mapping[str, object], key: str) -> str:
    return str(config.get(key) or "").strip()


def _first_float(payload: dict[str, object], *keys: str) -> float | None:
    for key in keys:
        if key in payload:
            value = payload.get(key)
            if value is not None and str(value).strip():
                return _coerce_float(value)
    return None


def _format_cny_amount(amount: float) -> str:
    return f"{float(amount):.2f}"


def _canonicalize_alipay_request_params(params: Mapping[str, object]) -> str:
    return _canonicalize_alipay_params(params, excluded_keys={"sign"})


def _canonicalize_alipay_callback_params(params: Mapping[str, object]) -> str:
    return _canonicalize_alipay_params(params, excluded_keys={"sign", "sign_type"})


def _canonicalize_alipay_params(
    params: Mapping[str, object],
    *,
    excluded_keys: set[str],
) -> str:
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if key in excluded_keys:
            continue
        if value is None:
            continue
        text = str(value)
        if not text:
            continue
        pairs.append((key, text))
    return "&".join(f"{key}={value}" for key, value in sorted(pairs))


def _normalize_private_key_pem(value: str) -> bytes:
    return _normalize_private_key_pem_candidates(value)[0]


def _normalize_private_key_pem_candidates(value: str) -> list[bytes]:
    text = value.strip().replace("\\n", "\n")
    if _pem_marker("BEGIN", "PRIVATE KEY") in text:
        return [text.encode("utf-8")]
    if _pem_marker("BEGIN", "RSA PRIVATE KEY") in text:
        return [text.encode("utf-8")]
    compact = "".join(text.split())
    lines = [compact[index : index + 64] for index in range(0, len(compact), 64)]
    body = "\n".join(lines)
    pkcs8_pem = (
        f"{_pem_marker('BEGIN', 'PRIVATE KEY')}\n"
        f"{body}\n"
        f"{_pem_marker('END', 'PRIVATE KEY')}\n"
    )
    pkcs1_pem = (
        f"{_pem_marker('BEGIN', 'RSA PRIVATE KEY')}\n"
        f"{body}\n"
        f"{_pem_marker('END', 'RSA PRIVATE KEY')}\n"
    )
    return [
        pkcs8_pem.encode(),
        pkcs1_pem.encode(),
    ]


def _load_alipay_private_key(value: str) -> object:
    errors: list[Exception] = []
    for pem in _normalize_private_key_pem_candidates(value):
        try:
            return serialization.load_pem_private_key(pem, password=None)
        except (TypeError, ValueError, UnsupportedAlgorithm) as error:
            errors.append(error)
    raise CommercialValidationError(
        "service.alipay_private_key_format_invalid",
        (
            "支付宝应用私钥格式无效。请填写应用私钥，支持 PEM 格式或支付宝工具"
            "导出的裸 Base64 私钥；不要填写支付宝公钥、应用公钥或证书。"
        ),
    ) from (errors[-1] if errors else None)


def _load_alipay_public_key(value: str) -> object:
    try:
        return serialization.load_pem_public_key(_normalize_public_key_pem(value))
    except (TypeError, ValueError, UnsupportedAlgorithm) as error:
        raise CommercialValidationError(
            "service.alipay_public_key_format_invalid",
            (
                "支付宝公钥格式无效。请填写支付宝开放平台提供的支付宝公钥，支持 PEM "
                "格式或裸 Base64 公钥；不要填写应用公钥、应用私钥或证书。"
            ),
        ) from error


def _normalize_public_key_pem(value: str) -> bytes:
    return _normalize_pem(
        value,
        begin_marker=_pem_marker("BEGIN", "PUBLIC KEY"),
        end_marker=_pem_marker("END", "PUBLIC KEY"),
    )


def _pem_marker(edge: str, key_type: str) -> str:
    return f"-----{edge} {key_type}-----"


def _normalize_pem(value: str, *, begin_marker: str, end_marker: str) -> bytes:
    text = value.strip().replace("\\n", "\n")
    if begin_marker in text:
        return text.encode("utf-8")
    compact = "".join(text.split())
    lines = [compact[index : index + 64] for index in range(0, len(compact), 64)]
    body = "\n".join(lines)
    return f"{begin_marker}\n{body}\n{end_marker}\n".encode()


def _coerce_float(value: object) -> float:
    if not isinstance(value, int | float | str):
        return 0.0
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0


def _first_datetime(payload: dict[str, object], *keys: str) -> datetime | None:
    for key in keys:
        value = payload.get(key)
        if not value:
            continue
        if isinstance(value, datetime):
            return value
        parsed = _parse_datetime_text(str(value))
        if parsed is not None:
            return parsed
    return None


def _parse_datetime_text(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    for candidate in (text, text.replace(" ", "T")):
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ALIPAY_GATEWAY_TIMEZONE)
            return parsed.astimezone(UTC)
        except ValueError:
            continue
    return None
