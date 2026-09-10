"""Deterministic quote-backed simulated fills with no broker submission."""

import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import SimulatedFill

IST=ZoneInfo("Asia/Kolkata")


class SimulatedFillModel:
    def __init__(self, clock=None): self.clock=clock or (lambda:datetime.now(IST))

    def fill(self, *, intent_id, contract, side, quantity=None):
        requested=int(quantity or contract.lot_size)
        if requested<=0 or requested>contract.lot_size: raise ValueError("simulated fill quantity exceeds one lot")
        if side=="BUY": price=contract.top_ask_price or contract.ltp; source="TOP_ASK" if contract.top_ask_price else "LTP"
        elif side=="SELL": price=contract.top_bid_price or contract.ltp; source="TOP_BID" if contract.top_bid_price else "LTP"
        else: raise ValueError("invalid simulated fill side")
        available=contract.top_ask_quantity if side=="BUY" else contract.top_bid_quantity
        filled=min(requested,available) if isinstance(available,int) and available>0 else requested
        now=self.clock().isoformat(); fill_id="paperfill_"+hashlib.sha256(f"{intent_id}|{side}|{filled}|{price}".encode()).hexdigest()[:20]
        return SimulatedFill(fill_id,intent_id,now,filled,float(price),float(price),source,"TOP_OF_BOOK_OR_LTP_V1",filled<requested)
