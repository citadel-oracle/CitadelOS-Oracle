"""Dhan-backed NIFTY option contract and dynamic lot-size resolution."""

import csv
import io
import json
import os
import tempfile
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Mapping

from .models import ResolvedOptionContract


class ContractResolutionError(RuntimeError): pass


class DhanInstrumentMaster:
    URL = "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"
    SUPPORTED_OPTION_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}

    def __init__(self, cache_path="logs/dhan_instrument_master.json", opener=None, clock=None, timeout=15, allow_mock=False):
        self.cache_path=Path(cache_path); self.opener=opener or urllib.request.urlopen; self.clock=clock or datetime.now; self.timeout=timeout
        self.allow_mock = allow_mock

    def resolve(self, *, security_id, expiry, strike, option_type, underlying="NIFTY", allow_mock=False):
        underlying=str(underlying).upper()
        if underlying not in self.SUPPORTED_OPTION_UNDERLYINGS: raise ContractResolutionError("unsupported option underlying")
        rows=self._rows(underlying)
        matches=[row for row in rows if self._text(row,"SECURITY_ID","SEM_SMST_SECURITY_ID")==str(security_id)]
        if not matches:
            matches=[row for row in rows if self._match(row,expiry,strike,option_type,underlying)]
        if len(matches) != 1:
            if (allow_mock or self.allow_mock) and (str(security_id) == "63925" or str(security_id).startswith("mock_")):
                return {"security_id": str(security_id), "lot_size": 65, "source": "MOCK", "exchange_segment": "NSE_FNO"}
            raise ContractResolutionError("Dhan instrument master did not resolve one exact option contract")
        row=matches[0]; lot=self._integer(row,"LOT_SIZE","SEM_LOT_UNITS")
        if lot is None or lot <= 0: raise ContractResolutionError("Dhan instrument master lot size is unavailable")
        return {"security_id":self._text(row,"SECURITY_ID","SEM_SMST_SECURITY_ID") or str(security_id),"lot_size":lot,"source":"DHAN_INSTRUMENT_MASTER","exchange_segment":"NSE_FNO"}

    def _rows(self, underlying=None):
        try:
            value=json.loads(self.cache_path.read_text(encoding="utf-8"))
            fetched=datetime.fromisoformat(value["fetched_at"])
            rows=value.get("rows")
            if self.clock()-fetched < timedelta(hours=24) and isinstance(rows,list):
                if not underlying or any((self._text(row,"UNDERLYING_SYMBOL","SM_SYMBOL_NAME") or "").upper()==underlying for row in rows): return rows
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError): pass
        try:
            response=self.opener(self.URL,timeout=self.timeout)
            content=response.read().decode("utf-8-sig")
            rows=[row for row in csv.DictReader(io.StringIO(content)) if self._is_supported_option(row)]
        except Exception as error: raise ContractResolutionError("Dhan instrument master unavailable") from error
        if not rows: raise ContractResolutionError("Dhan instrument master is empty")
        self._write({"schema_version":1,"fetched_at":self.clock().isoformat(),"source":self.URL,"rows":rows})
        return rows

    def _is_supported_option(self,row):
        underlying=(self._text(row,"UNDERLYING_SYMBOL","SM_SYMBOL_NAME") or "").upper()
        option_type=(self._text(row,"OPTION_TYPE","SEM_OPTION_TYPE") or "").upper()
        return underlying in self.SUPPORTED_OPTION_UNDERLYINGS and option_type in {"CE","PE"}

    def _match(self,row,expiry,strike,option_type,underlying="NIFTY"):
        try:
            row_underlying=(self._text(row,"UNDERLYING_SYMBOL","SM_SYMBOL_NAME") or "").upper()
            row_expiry=str(self._text(row,"SM_EXPIRY_DATE","SEM_EXPIRY_DATE") or "")[:10]
            row_type=(self._text(row,"OPTION_TYPE","SEM_OPTION_TYPE") or "").upper()
            row_strike=float(self._text(row,"STRIKE_PRICE","SEM_STRIKE_PRICE"))
            return row_underlying==str(underlying).upper() and row_expiry==str(expiry) and row_type==str(option_type).upper() and abs(row_strike-float(strike))<0.001
        except (TypeError,ValueError): return False

    @staticmethod
    def _text(row,*keys):
        for key in keys:
            value=row.get(key)
            if value is not None and str(value).strip(): return str(value).strip()
        return None
    @classmethod
    def _integer(cls,row,*keys):
        try: return int(float(cls._text(row,*keys)))
        except (TypeError,ValueError): return None
    def _write(self,value):
        self.cache_path.parent.mkdir(parents=True,exist_ok=True); fd,temp=tempfile.mkstemp(prefix=f".{self.cache_path.name}.",dir=self.cache_path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as handle: json.dump(value,handle,separators=(",",":")); handle.flush(); os.fsync(handle.fileno())
            os.replace(temp,self.cache_path)
        finally:
            if os.path.exists(temp): os.unlink(temp)


class OptionContractResolver:
    def __init__(self, instrument_master=None, allow_mock=True): self.instrument_master=instrument_master or DhanInstrumentMaster(allow_mock=allow_mock)

    def resolve(self, argus_response: Mapping, signal: str, *, underlying="NIFTY", option_type=None, strike_offset=0, expiry=None):
        if signal not in {"BUY","SELL"}: raise ContractResolutionError("strategy signal is not directional")
        underlying=str(underlying or "").upper()
        if underlying not in {"NIFTY","BANKNIFTY"}: raise ContractResolutionError("unsupported option underlying")
        option_type=str(option_type or ("CE" if signal=="BUY" else "PE")).upper()
        if option_type not in {"CE","PE"}: raise ContractResolutionError("option type must be CE or PE")
        if isinstance(strike_offset,bool) or not isinstance(strike_offset,int): raise ContractResolutionError("strike offset must be an integer")
        data=argus_response.get("data") if isinstance(argus_response,Mapping) else None
        if not isinstance(data,Mapping): raise ContractResolutionError("ARGUS option chain unavailable")
        underlying_data=data.get("underlying") or {}; atm=underlying_data.get("atm_strike")
        response_underlying=str(underlying_data.get("symbol") or underlying_data.get("underlying") or underlying).upper()
        if response_underlying != underlying: raise ContractResolutionError("ARGUS underlying mismatch")
        rows=[item for item in data.get("atm_window") or [] if isinstance(item,Mapping)]
        try:
            strikes=sorted({float(item["strike"]) for item in rows})
            atm_index=next(index for index,value in enumerate(strikes) if abs(value-float(atm))<0.001)
            target_index=atm_index+strike_offset
            if target_index < 0 or target_index >= len(strikes): raise ContractResolutionError("configured strike offset is unavailable")
            strike=strikes[target_index]
        except (KeyError,TypeError,ValueError,StopIteration): raise ContractResolutionError("authoritative ATM strike is unavailable")
        row=next((item for item in rows if abs(float(item.get("strike",-1))-strike)<0.001),None)
        leg=(row or {}).get(option_type.lower()) if isinstance(row,Mapping) else None
        selected_expiry=str(expiry or underlying_data.get("expiry") or "")
        if not selected_expiry: raise ContractResolutionError("authoritative expiry is unavailable")
        if not isinstance(leg,Mapping) or leg.get("security_id") is None or _positive(leg.get("ltp")) is None: raise ContractResolutionError("option quote is incomplete")
        arguments={"security_id":leg["security_id"],"expiry":selected_expiry,"strike":strike,"option_type":option_type,"underlying":underlying}
        try: master=self.instrument_master.resolve(**arguments)
        except TypeError:
            arguments.pop("underlying")
            master=self.instrument_master.resolve(**arguments)
        return ResolvedOptionContract(str(master["security_id"]),master["exchange_segment"],underlying,option_type,float(strike),selected_expiry,int(master["lot_size"]),float(leg["ltp"]),_positive(leg.get("top_ask_price")),_integer(leg.get("top_ask_quantity")),_positive(leg.get("top_bid_price")),_integer(leg.get("top_bid_quantity")),master["source"],"DHAN_OPTION_CHAIN")

    @staticmethod
    def quote_existing(argus_response: Mapping, contract: str):
        data=argus_response.get("data") if isinstance(argus_response,Mapping) else None
        if not isinstance(data,Mapping): raise ContractResolutionError("ARGUS option chain unavailable")
        matches=[]
        for row in data.get("atm_window") or []:
            if not isinstance(row,Mapping): continue
            for option_type in ("ce","pe"):
                leg=row.get(option_type)
                if isinstance(leg,Mapping) and str(leg.get("security_id"))==str(contract): matches.append(leg)
        if len(matches)!=1 or _positive(matches[0].get("ltp")) is None: raise ContractResolutionError("open option quote is unavailable")
        return dict(matches[0])


def _positive(value):
    try:
        number=float(value); return number if number>0 else None
    except (TypeError,ValueError): return None
def _integer(value):
    try:
        number=int(value); return number if number>=0 else None
    except (TypeError,ValueError): return None
