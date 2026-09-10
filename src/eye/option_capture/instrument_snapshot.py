"""Instrument Master Snapshot Manager for Eye Engine Option Capture."""

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Tuple, Optional

from src.eye.option_evidence.identity import OptionContractIdentity
from src.eye.contracts import PriceAtom


class InstrumentSnapshotManager:
    def __init__(self, raw_metadata: bytes):
        self.raw_bytes = raw_metadata
        self.fingerprint = hashlib.sha256(raw_metadata).hexdigest()
        self.valid_contracts: Dict[str, OptionContractIdentity] = {}
        self.excluded_contracts: List[Dict[str, str]] = []

    @classmethod
    def load_from_file(cls, filepath: Path) -> "InstrumentSnapshotManager":
        content = filepath.read_bytes()
        return cls(content)

    def parse_nifty_options(self, effective_time: datetime) -> Tuple[Dict[str, OptionContractIdentity], List[Dict[str, str]]]:
        """Parses raw metadata, filtering and constructing exact OptionContractIdentity objects for NIFTY options."""
        self.valid_contracts.clear()
        self.excluded_contracts.clear()

        try:
            records = json.loads(self.raw_bytes.decode("utf-8"))
        except Exception:
            records = []

        if isinstance(records, dict) and "data" in records:
            records = records["data"]

        for item in records:
            symbol = str(item.get("trading_symbol") or item.get("symbol") or item.get("SEM_TRADING_SYMBOL") or "").upper()
            underlying = str(item.get("underlying") or item.get("SEM_CUSTOM_SYMBOL") or "").upper()

            # Exclude BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNEXT50
            if "BANKNIFTY" in symbol or "BANKNIFTY" in underlying:
                continue
            if "FINNIFTY" in symbol or "FINNIFTY" in underlying:
                continue
            if "MIDCPNIFTY" in symbol or "MIDCPNIFTY" in underlying:
                continue
            if "NIFTY" not in symbol and "NIFTY" not in underlying:
                continue

            sec_id = str(item.get("security_id") or item.get("SEM_SMST_SECURITY_ID") or "")
            opt_type = item.get("option_type") or item.get("SEM_OPTION_TYPE") or ""
            strike_val = item.get("strike") or item.get("SEM_STRIKE_PRICE") or 0.0
            exp_str = item.get("expiry") or item.get("SEM_EXPIRY_DATE") or ""
            lot_sz = item.get("lot_size") or item.get("SEM_LOT_UNITS") or 25
            tick_sz = item.get("tick_size") or 0.05

            if not sec_id or not opt_type or not exp_str or strike_val <= 0:
                self.excluded_contracts.append({
                    "security_id": sec_id,
                    "symbol": symbol,
                    "reason": "MISSING_MANDATORY_METADATA_FIELDS"
                })
                continue

            try:
                exp_dt = datetime.strptime(exp_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                cid = OptionContractIdentity.create(
                    exchange="NSE", segment="NSE_FO", security_id=sec_id,
                    underlying_security_id="13", underlying_symbol="NIFTY",
                    underlying_instrument_key="NSE:NIFTY:UNDERLYING_INDEX",
                    derivative_instrument_type="OPTIDX", option_type=opt_type.upper(),
                    expiry_date=exp_dt.date(), expiry_timestamp=exp_dt,
                    expiry_class="WEEKLY", strike=PriceAtom(ticks=int(round(float(strike_val) * 100))),
                    tick_size=PriceAtom(ticks=int(round(float(tick_sz) * 100))), lot_size=int(lot_sz),
                    source="DHAN_INSTRUMENT_MASTER", effective_time=effective_time,
                )
                self.valid_contracts[cid.contract_key] = cid
            except Exception as e:
                self.excluded_contracts.append({
                    "security_id": sec_id,
                    "symbol": symbol,
                    "reason": f"IDENTITY_CREATION_FAILED: {str(e)}"
                })

        return self.valid_contracts, self.excluded_contracts
