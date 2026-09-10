import os
import requests
from dotenv import load_dotenv

class OpenAlgoClient:
    def __init__(self, base_url=None, api_key=None):
        if not base_url:
            load_dotenv()
            base_url = os.getenv("OPENALGO_BASE_URL", "http://127.0.0.1:5001/api/v1")
            api_key = os.getenv("OPENALGO_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        
    def _post(self, endpoint, payload=None):
        body = payload or {}
        body["apikey"] = self.api_key
        response = requests.post(f"{self.base_url}{endpoint}", json=body, timeout=10)
        response.raise_for_status()
        return response.json()

    def get_analyzer_status(self):
        return self._post("/analyzer")

    def toggle_analyzer(self, mode: bool):
        return self._post("/analyzer/toggle", {"mode": mode})

    def place_order(self, order_payload):
        return self._post("/placeorder", order_payload)

    def modify_order(self, order_payload):
        return self._post("/modifyorder", order_payload)

    def cancel_order(self, order_payload):
        return self._post("/cancelorder", order_payload)

    def get_positions(self):
        return self._post("/positionbook")

    def get_orders(self):
        return self._post("/orderbook")

    def get_trades(self):
        return self._post("/tradebook")

    def get_funds(self):
        return self._post("/funds")
