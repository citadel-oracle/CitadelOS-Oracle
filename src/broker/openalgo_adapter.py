import json
from pathlib import Path
from typing import Any, Mapping, Optional, Iterable, Callable
from src.broker.live_foundation import LiveFoundationError, BrokerRuntimeConfig
from src.broker.openalgo_client import OpenAlgoClient
from src.risk.authorization import (
    RiskAuthorizationRequest,
    RiskAuthorizationService,
)

class OpenAlgoBrokerAdapter:
    provider_name = "OPENALGO"

    def __init__(self, dhan_adapter, openalgo_client=None, config=None):
        self.dhan_adapter = dhan_adapter
        self.client = openalgo_client or OpenAlgoClient()
        self.config = config or BrokerRuntimeConfig()
        self.session_state = "DISCONNECTED"
        self.last_error = None
        self.risk_authorizer = RiskAuthorizationService()
        
        # Load and validate settings
        settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.json"
        try:
            with settings_path.open("r") as f:
                settings = json.load(f)
        except Exception:
            settings = {}
            
        execution_provider = settings.get("execution_provider")
        analyzer_only = settings.get("openalgo_analyzer_only") is True
        
        # Enforce safety rules: If provider is OpenAlgo, it must be analyzer only!
        if execution_provider == "openalgo" and not analyzer_only:
            raise LiveFoundationError("Safety Violation: OpenAlgo Live Mode is prohibited. openalgo_analyzer_only must be true.")

        # Reject placeholder/empty keys
        api_key = self.client.api_key
        if not api_key or api_key in {"dummy_analyzer_key", "placeholder", ""}:
            raise LiveFoundationError("Authentication Blocked: Empty or placeholder OpenAlgo API key configured.")

    def authenticate(self) -> Mapping[str, Any]:
        try:
            # Reject empty/placeholder keys
            api_key = self.client.api_key
            if not api_key or api_key in {"dummy_analyzer_key", "placeholder", ""}:
                self.session_state = "AUTHENTICATION_FAILED"
                raise LiveFoundationError("Placeholder/Empty OpenAlgo API key configured.")

            status_response = self.client.get_analyzer_status()
            if not isinstance(status_response, Mapping):
                status_response = {}
            
            data = status_response.get("data")
            if not isinstance(data, Mapping):
                data = status_response
            
            # Safety gate: Fail closed if OpenAlgo is NOT already in Analyzer Mode
            if not data.get("analyze_mode", False) and not data.get("mode") == "analyze":
                self.session_state = "AUTHENTICATION_FAILED"
                raise LiveFoundationError("OpenAlgo is NOT running in Analyzer Mode. Automatic toggling is disabled. CITADEL has failed closed.")
            
            self.session_state = "AUTHENTICATED"
            return {"status": "CONNECTED", "mode": "ANALYZER", "details": status_response}
        except Exception as e:
            self.session_state = "AUTHENTICATION_FAILED"
            self.last_error = str(e)
            raise LiveFoundationError(f"OpenAlgo connection failed: {e}")

    def refresh_token(self) -> Mapping[str, Any]:
        return {"status": "SUCCESS", "provider": "OPENALGO"}

    # Execution Delegation to OpenAlgo Client
    def place_order(self, payload: Mapping[str, Any], risk_context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        self.config.assert_live_mutation_allowed()
        
        # Double check OpenAlgo mode is still analyze
        self._assert_analyzer_mode()
        
        # Check risk authorization gates
        request = RiskAuthorizationRequest.from_broker_mutation(
            method="POST",
            endpoint="/orders",
            payload=dict(payload),
            risk_context=risk_context,
        )
        decision = self.risk_authorizer.authorize(request)
        if not decision.allowed:
            raise LiveFoundationError(f"Citadel Risk Gate Blocked Order: {decision.reason}")
        
        openalgo_payload = self._translate_order_payload(payload)
        response = self.client.place_order(openalgo_payload)
        return self._checked(response, "order placement")

    def modify_order(self, order_id: str, payload: Mapping[str, Any], risk_context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        self.config.assert_live_mutation_allowed()
        
        self._assert_analyzer_mode()
        
        request = RiskAuthorizationRequest.from_broker_mutation(
            method="PUT",
            endpoint=f"/orders/{order_id}",
            payload=dict(payload),
            risk_context=risk_context,
        )
        decision = self.risk_authorizer.authorize(request)
        if not decision.allowed:
            raise LiveFoundationError(f"Citadel Risk Gate Blocked Modify: {decision.reason}")

        openalgo_payload = self._translate_modify_payload(order_id, payload)
        response = self.client.modify_order(openalgo_payload)
        return self._checked(response, "order modification")

    def cancel_order(self, order_id: str, risk_context: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        self.config.assert_live_mutation_allowed()
        
        self._assert_analyzer_mode()
        
        request = RiskAuthorizationRequest.from_broker_mutation(
            method="DELETE",
            endpoint=f"/orders/{order_id}",
            risk_context=risk_context,
        )
        decision = self.risk_authorizer.authorize(request)
        if not decision.allowed:
            raise LiveFoundationError(f"Citadel Risk Gate Blocked Cancel: {decision.reason}")

        response = self.client.cancel_order({"orderid": order_id})
        return self._checked(response, "order cancellation")

    # Read-Only Operations
    def orders(self) -> list[Mapping[str, Any]]:
        response = self.client.get_orders()
        data = response.get("data") if isinstance(response, Mapping) else None
        raw_orders = data.get("orders") if isinstance(data, Mapping) else None
        if not isinstance(raw_orders, list):
            raise LiveFoundationError("OpenAlgo order book unavailable")
        return [self._translate_to_citadel_order(o) for o in raw_orders if isinstance(o, Mapping)]

    def positions(self) -> list[Mapping[str, Any]]:
        response = self.client.get_positions()
        raw_positions = response.get("data") if isinstance(response, Mapping) else None
        if not isinstance(raw_positions, list):
            raise LiveFoundationError("OpenAlgo positions unavailable")
        return [self._translate_to_citadel_position(p) for p in raw_positions if isinstance(p, Mapping)]

    def order(self, order_id: str) -> Mapping[str, Any]:
        all_orders = self.orders()
        for o in all_orders:
            if str(o.get("orderId")) == str(order_id):
                return o
        raise LiveFoundationError(f"Order {order_id} not found in OpenAlgo")

    def order_by_correlation_id(self, correlation_id: str) -> Optional[Mapping[str, Any]]:
        for o in self.orders():
            if str(o.get("correlationId")) == str(correlation_id):
                return o
        return None

    # Market Data Delegation (routes to underlying Dhan adapter)
    def connect_quotes(self, instruments: Iterable[Mapping[str, str]], handler: Callable[[Any], None]) -> None:
        self.dhan_adapter.connect_quotes(instruments, handler)

    def disconnect_quotes(self) -> None:
        self.dhan_adapter.disconnect_quotes()

    # Helpers and Translators
    def _assert_analyzer_mode(self):
        status_response = self.client.get_analyzer_status()
        if not isinstance(status_response, Mapping):
            status_response = {}
        data = status_response.get("data")
        if not isinstance(data, Mapping):
            data = status_response
            
        if not data.get("analyze_mode", False) and not data.get("mode") == "analyze":
            raise LiveFoundationError("Safety Violation: OpenAlgo is NOT running in Analyzer Mode. Mutation rejected.")

    @staticmethod
    def _checked(response: Any, operation: str) -> Mapping[str, Any]:
        if not isinstance(response, Mapping) or response.get("status") in {"error", "failed"} or response.get("error"):
            error_msg = response.get("message") or response.get("error") or "Unknown error"
            raise LiveFoundationError(f"OpenAlgo {operation} failed: {error_msg}")
        return dict(response)

    def _translate_order_payload(self, citadel_payload: Mapping[str, Any]) -> dict:
        citadel_exchange = citadel_payload.get("exchangeSegment") or ""
        exchange = "NFO" if "FNO" in str(citadel_exchange).upper() else "NSE"
        
        citadel_product = str(citadel_payload.get("productType") or "").upper()
        if "INTRADAY" in citadel_product:
            product = "MIS"
        elif "CNC" in citadel_product:
            product = "CNC"
        elif "MARGIN" in citadel_product:
            product = "NRML"
        else:
            product = "MIS"

        citadel_order_type = str(citadel_payload.get("orderType") or "").upper()
        if "LIMIT" in citadel_order_type:
            pricetype = "LIMIT"
        elif "STOP" in citadel_order_type:
            pricetype = "SL"
        else:
            pricetype = "MARKET"

        correlation_id = citadel_payload.get("correlationId") or ""
        strategy = f"Citadel:{correlation_id}" if correlation_id else "Citadel"
            
        return {
            "strategy": strategy,
            "symbol": citadel_payload.get("tradingSymbol") or str(citadel_payload.get("securityId")),
            "exchange": exchange,
            "action": citadel_payload.get("transactionType"),
            "quantity": int(citadel_payload.get("quantity", 1)),
            "product": product,
            "pricetype": pricetype,
            "price": float(citadel_payload["price"]) if citadel_payload.get("price") else 0.0,
            "trigger_price": float(citadel_payload["triggerPrice"]) if citadel_payload.get("triggerPrice") else 0.0
        }

    def _translate_modify_payload(self, order_id: str, citadel_payload: Mapping[str, Any]) -> dict:
        return {
            "orderid": order_id,
            "price": float(citadel_payload["price"]) if citadel_payload.get("price") else 0.0,
            "quantity": int(citadel_payload.get("quantity", 1))
        }

    def _translate_to_citadel_order(self, openalgo_order: Mapping[str, Any]) -> dict:
        strategy_field = openalgo_order.get("strategy") or ""
        correlation_id = None
        if ":" in strategy_field:
            parts = strategy_field.split(":", 1)
            correlation_id = parts[1]

        return {
            "orderId": openalgo_order.get("orderid") or openalgo_order.get("id"),
            "orderStatus": (openalgo_order.get("order_status") or openalgo_order.get("status") or "PENDING").upper(),
            "correlationId": correlation_id,
            "tradingSymbol": openalgo_order.get("symbol"),
            "price": openalgo_order.get("price"),
            "quantity": openalgo_order.get("quantity"),
            "transactionType": openalgo_order.get("action") or openalgo_order.get("transaction_type")
        }

    def _translate_to_citadel_position(self, openalgo_pos: Mapping[str, Any]) -> dict:
        return {
            "securityId": openalgo_pos.get("symbol"),
            "exchangeSegment": "NSE_FNO" if openalgo_pos.get("exchange") == "NFO" else "NSE_EQ",
            "netQty": int(openalgo_pos.get("quantity") or openalgo_pos.get("netQty", 0)),
            "realized_pnl": float(openalgo_pos.get("pnl") or openalgo_pos.get("realized_pnl", 0.0))
        }
