"""ARGUS option-chain intelligence backed by live Dhan data."""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from src.argus.baseline_store import ArgusBaselineStore
from src.broker.dhan_client import DhanClient


class OptionChainDataError(RuntimeError):
    """Raised when Dhan cannot supply a usable option-chain snapshot."""


class InvalidOptionExpiryError(OptionChainDataError):
    """Raised when a requested expiry is not active for the underlying."""


@dataclass(frozen=True)
class OptionLegSnapshot:
    security_id: Optional[int]
    ltp: Optional[float]
    previous_close: Optional[float]
    price_change: Optional[float]
    day_price_change: Optional[float]
    intraday_price_change: Optional[float]
    oi: Optional[int]
    previous_oi: Optional[int]
    change_oi: Optional[int]
    day_change_oi: Optional[int]
    intraday_change_oi: Optional[int]
    baseline_oi: Optional[int]
    baseline_ltp: Optional[float]
    volume: Optional[int]
    previous_volume: Optional[int]
    average_price: Optional[float]
    iv: Optional[float]
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    top_ask_price: Optional[float] = None
    top_ask_quantity: Optional[int] = None
    top_bid_price: Optional[float] = None
    top_bid_quantity: Optional[int] = None
    change_oi_basis: str = "previous_day"
    intraday_change_oi_basis: str = "session_baseline"
    day_positioning: str = "NEUTRAL"
    day_activity: str = "NEUTRAL"
    positioning: str = "NEUTRAL"
    activity: str = "NEUTRAL"


@dataclass(frozen=True)
class OptionStrikeSnapshot:
    strike: float
    ce_moneyness: str
    pe_moneyness: str
    ce: OptionLegSnapshot
    pe: OptionLegSnapshot


@dataclass(frozen=True)
class OptionChainTotals:
    ce_oi: int
    pe_oi: int
    ce_change_oi: int
    pe_change_oi: int
    day_ce_change_oi: int
    day_pe_change_oi: int
    intraday_ce_change_oi: Optional[int]
    intraday_pe_change_oi: Optional[int]
    pcr: Optional[float]
    change_pcr: Optional[float]
    day_change_pcr: Optional[float]
    intraday_change_pcr: Optional[float]


@dataclass(frozen=True)
class OptionChainLevel:
    strike: float
    value: int


@dataclass(frozen=True)
class OptionChainWalls:
    highest_ce_oi: Optional[OptionChainLevel]
    highest_pe_oi: Optional[OptionChainLevel]
    highest_ce_change_oi: Optional[OptionChainLevel]
    highest_pe_change_oi: Optional[OptionChainLevel]
    highest_intraday_ce_oi_addition: Optional[OptionChainLevel]
    highest_intraday_pe_oi_addition: Optional[OptionChainLevel]
    strongest_ce_unwind: Optional[OptionChainLevel]
    strongest_pe_unwind: Optional[OptionChainLevel]


@dataclass(frozen=True)
class ArgusDominance:
    call_writing_score: float
    put_writing_score: float
    call_buying_score: float
    put_buying_score: float
    writer_dominance_percentage: float
    buyer_dominance_percentage: float
    evidence_coverage_percentage: float
    formula: str


@dataclass(frozen=True)
class ArgusVerdict:
    regime: str
    bias: str
    preferred_option_side: str
    confidence: int
    reasons: list[str]
    call_wall: Optional[OptionChainLevel]
    put_wall: Optional[OptionChainLevel]
    breakout_above: Optional[float]
    breakdown_below: Optional[float]
    avoid_zone: Optional[dict[str, float]]
    confidence_formula: str


@dataclass(frozen=True)
class OptionChainSnapshot:
    symbol: str
    underlying_security_id: int
    underlying_segment: str
    underlying_ltp: float
    expiry: str
    fetched_at: str
    source_event_time: Optional[str]
    receipt_timestamp: str
    timestamp_semantics: str
    market_state: str
    session_name: str
    trading_date: str
    baseline_timestamp: Optional[str]
    baseline_status: str
    atm_strike: float
    ce_itm_strikes: list[float]
    ce_otm_strikes: list[float]
    pe_itm_strikes: list[float]
    pe_otm_strikes: list[float]
    totals: OptionChainTotals
    walls: OptionChainWalls
    dominance: ArgusDominance
    verdict: ArgusVerdict
    atm_window: list[OptionStrikeSnapshot] = field(default_factory=list)
    strikes: list[OptionStrikeSnapshot] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OptionChainEngine:
    EXCHANGE_TIMEZONE = ZoneInfo("Asia/Kolkata")
    MIN_PRICE_CHANGE = 0.05
    MIN_OI_CHANGE = 1

    def __init__(self, dhan=None, baseline_store=None, now_provider=None):
        self.dhan = dhan if dhan is not None else DhanClient()
        self.now_provider = now_provider or (
            lambda: datetime.now(self.EXCHANGE_TIMEZONE)
        )
        self.baseline_store = baseline_store or ArgusBaselineStore(
            now_provider=self.now_provider
        )

    def fetch_current_snapshot(
        self,
        symbol,
        segment,
        security_id,
        expiry=None,
    ):
        selected_expiry = self._select_expiry(segment, security_id, expiry)
        response = self.dhan.get_option_chain(
            segment=segment,
            security_id=security_id,
            expiry=selected_expiry,
        )
        return self.build_snapshot(
            symbol=symbol,
            segment=segment,
            security_id=security_id,
            expiry=selected_expiry,
            response=response,
        )

    def active_expiries(self, segment, security_id):
        response = self.dhan.get_option_expiries(
            segment=segment,
            security_id=security_id,
        )
        self._raise_for_dhan_error(response, "expiry list")
        expiries = response.get("data")
        if not isinstance(expiries, list):
            raise OptionChainDataError("Dhan expiry list returned no dates")

        today = self._now().date()
        active = []
        for value in expiries:
            try:
                parsed = date.fromisoformat(str(value))
            except ValueError:
                continue
            if parsed >= today:
                active.append(parsed.isoformat())
        if not active:
            raise OptionChainDataError("Dhan returned no current or future expiry")
        return sorted(set(active))

    def build_snapshot(self, symbol, segment, security_id, expiry, response):
        self._raise_for_dhan_error(response, "option chain")
        data = response.get("data")
        if not isinstance(data, dict):
            raise OptionChainDataError("Dhan option chain returned no data object")

        underlying_ltp = self._number(data.get("last_price"))
        raw_chain = data.get("oc")
        if underlying_ltp is None or not isinstance(raw_chain, dict) or not raw_chain:
            raise OptionChainDataError(
                "Dhan option chain is missing underlying LTP or strike data"
            )

        raw_strikes = []
        missing_fields = set()
        observations = []
        for raw_strike, raw_legs in raw_chain.items():
            strike = self._number(raw_strike)
            if strike is None or not isinstance(raw_legs, dict):
                continue
            parsed_legs = {}
            for side in ("CE", "PE"):
                values = self._raw_leg(
                    raw_legs.get(side.lower()), side, strike, missing_fields
                )
                parsed_legs[side] = values
                observations.append(
                    {
                        "strike": strike,
                        "side": side,
                        "oi": values["oi"],
                        "ltp": values["ltp"],
                    }
                )
            raw_strikes.append((strike, parsed_legs))

        if not raw_strikes:
            raise OptionChainDataError("Dhan option chain contains no valid strikes")

        raw_strikes.sort(key=lambda item: item[0])
        strike_values = [item[0] for item in raw_strikes]
        atm_strike = min(strike_values, key=lambda strike: abs(strike - underlying_ltp))
        strike_windows = self._strike_windows(strike_values, atm_strike)
        fetched_at = self._now()
        baseline = self.baseline_store.resolve(
            symbol=str(symbol),
            expiry=str(expiry),
            observations=observations,
            now=fetched_at,
        )

        strikes = []
        for strike, parsed_legs in raw_strikes:
            ce = self._build_leg(
                parsed_legs["CE"],
                "CE",
                baseline.records.get((strike, "CE")),
            )
            pe = self._build_leg(
                parsed_legs["PE"],
                "PE",
                baseline.records.get((strike, "PE")),
            )
            strikes.append(
                OptionStrikeSnapshot(
                    strike=strike,
                    ce_moneyness=self._moneyness("CE", strike, atm_strike),
                    pe_moneyness=self._moneyness("PE", strike, atm_strike),
                    ce=ce,
                    pe=pe,
                )
            )

        atm_window_strikes = {
            atm_strike,
            *strike_windows["ce_itm"],
            *strike_windows["ce_otm"],
        }
        atm_window = [
            strike for strike in strikes if strike.strike in atm_window_strikes
        ]
        totals = self._totals(strikes)
        walls = self._walls(strikes)
        dominance, raw_scores = self._dominance(atm_window)
        verdict = self._verdict(
            dominance=dominance,
            raw_scores=raw_scores,
            walls=walls,
            baseline_timestamp=baseline.baseline_timestamp,
        )

        if baseline.baseline_timestamp is None:
            baseline_status = (
                "UNAVAILABLE_OUTSIDE_SESSION"
                if baseline.market_state != "OPEN"
                else "INCOMPLETE"
            )
        else:
            baseline_status = "ESTABLISHED" if baseline.created else "AVAILABLE"

        return OptionChainSnapshot(
            symbol=str(symbol),
            underlying_security_id=int(security_id),
            underlying_segment=str(segment),
            underlying_ltp=underlying_ltp,
            expiry=str(expiry),
            fetched_at=fetched_at.isoformat(),
            source_event_time=None,
            receipt_timestamp=fetched_at.isoformat(),
            timestamp_semantics="RECEIPT_TIME_NO_PROVIDER_EVENT_TIME",
            market_state=baseline.market_state,
            session_name="NSE_BSE_REGULAR",
            trading_date=baseline.trading_date,
            baseline_timestamp=baseline.baseline_timestamp,
            baseline_status=baseline_status,
            atm_strike=atm_strike,
            ce_itm_strikes=strike_windows["ce_itm"],
            ce_otm_strikes=strike_windows["ce_otm"],
            pe_itm_strikes=strike_windows["pe_itm"],
            pe_otm_strikes=strike_windows["pe_otm"],
            totals=totals,
            walls=walls,
            dominance=dominance,
            verdict=verdict,
            atm_window=atm_window,
            strikes=strikes,
            missing_fields=sorted(missing_fields),
        )

    def prepare_snapshot_input(self, symbol, segment, security_id, expiry, response):
        """Capture immutable provider/baseline input before CPU-only projection work."""

        self._raise_for_dhan_error(response, "option chain")
        data = response.get("data")
        if not isinstance(data, dict):
            raise OptionChainDataError("Dhan option chain returned no data object")
        underlying_ltp = self._number(data.get("last_price"))
        raw_chain = data.get("oc")
        if underlying_ltp is None or not isinstance(raw_chain, dict) or not raw_chain:
            raise OptionChainDataError(
                "Dhan option chain is missing underlying LTP or strike data"
            )

        raw_strikes = []
        missing_fields = set()
        observations = []
        for raw_strike, raw_legs in raw_chain.items():
            strike = self._number(raw_strike)
            if strike is None or not isinstance(raw_legs, dict):
                continue
            parsed_legs = {}
            for side in ("CE", "PE"):
                values = self._raw_leg(raw_legs.get(side.lower()), side, strike, missing_fields)
                parsed_legs[side] = values
                observations.append({"strike": strike, "side": side, "oi": values["oi"], "ltp": values["ltp"]})
            raw_strikes.append((strike, parsed_legs))
        if not raw_strikes:
            raise OptionChainDataError("Dhan option chain contains no valid strikes")

        raw_strikes.sort(key=lambda item: item[0])
        strike_values = [item[0] for item in raw_strikes]
        atm_strike = min(strike_values, key=lambda strike: abs(strike - underlying_ltp))
        fetched_at = self._now()
        baseline = self.baseline_store.resolve(
            symbol=str(symbol), expiry=str(expiry), observations=observations, now=fetched_at,
        )
        return {
            "symbol": str(symbol), "segment": str(segment), "security_id": int(security_id),
            "expiry": str(expiry), "underlying_ltp": underlying_ltp,
            "raw_strikes": raw_strikes, "missing_fields": sorted(missing_fields),
            "atm_strike": atm_strike, "fetched_at": fetched_at.isoformat(),
            "baseline": {
                "records": baseline.records,
                "baseline_timestamp": baseline.baseline_timestamp,
                "created": baseline.created,
                "market_state": baseline.market_state,
                "trading_date": baseline.trading_date,
            },
        }

    def build_prepared_snapshot(self, prepared):
        """Build the projection from a serializable immutable input snapshot."""

        raw_strikes = prepared["raw_strikes"]
        atm_strike = prepared["atm_strike"]
        baseline = prepared["baseline"]
        strike_values = [item[0] for item in raw_strikes]
        strike_windows = self._strike_windows(strike_values, atm_strike)
        strikes = []
        for strike, parsed_legs in raw_strikes:
            ce = self._build_leg(parsed_legs["CE"], "CE", baseline["records"].get((strike, "CE")))
            pe = self._build_leg(parsed_legs["PE"], "PE", baseline["records"].get((strike, "PE")))
            strikes.append(OptionStrikeSnapshot(
                strike=strike,
                ce_moneyness=self._moneyness("CE", strike, atm_strike),
                pe_moneyness=self._moneyness("PE", strike, atm_strike),
                ce=ce, pe=pe,
            ))
        atm_window_strikes = {atm_strike, *strike_windows["ce_itm"], *strike_windows["ce_otm"]}
        atm_window = [strike for strike in strikes if strike.strike in atm_window_strikes]
        totals = self._totals(strikes)
        walls = self._walls(strikes)
        dominance, raw_scores = self._dominance(atm_window)
        verdict = self._verdict(
            dominance=dominance, raw_scores=raw_scores, walls=walls,
            baseline_timestamp=baseline["baseline_timestamp"],
        )
        if baseline["baseline_timestamp"] is None:
            baseline_status = "UNAVAILABLE_OUTSIDE_SESSION" if baseline["market_state"] != "OPEN" else "INCOMPLETE"
        else:
            baseline_status = "ESTABLISHED" if baseline["created"] else "AVAILABLE"
        return OptionChainSnapshot(
            symbol=prepared["symbol"], underlying_security_id=prepared["security_id"],
            underlying_segment=prepared["segment"], underlying_ltp=prepared["underlying_ltp"],
            expiry=prepared["expiry"], fetched_at=prepared["fetched_at"],
            source_event_time=None, receipt_timestamp=prepared["fetched_at"],
            timestamp_semantics="RECEIPT_TIME_NO_PROVIDER_EVENT_TIME",
            market_state=baseline["market_state"], session_name="NSE_BSE_REGULAR",
            trading_date=baseline["trading_date"], baseline_timestamp=baseline["baseline_timestamp"],
            baseline_status=baseline_status, atm_strike=atm_strike,
            ce_itm_strikes=strike_windows["ce_itm"], ce_otm_strikes=strike_windows["ce_otm"],
            pe_itm_strikes=strike_windows["pe_itm"], pe_otm_strikes=strike_windows["pe_otm"],
            totals=totals, walls=walls, dominance=dominance, verdict=verdict,
            atm_window=atm_window, strikes=strikes, missing_fields=prepared["missing_fields"],
        )

    def _select_expiry(self, segment, security_id, requested):
        expiries = self.active_expiries(segment, security_id)
        if requested is None:
            return expiries[0]
        requested_value = str(requested)
        if requested_value not in expiries:
            raise InvalidOptionExpiryError(
                f"Expiry {requested_value} is not active for security {security_id}"
            )
        return requested_value

    def _raw_leg(self, raw_leg, option_type, strike, missing_fields):
        if not isinstance(raw_leg, dict):
            missing_fields.add(f"{strike:g}.{option_type.lower()}")
            raw_leg = {}

        greeks = raw_leg.get("greeks") if isinstance(raw_leg.get("greeks"), dict) else {}
        values = {
            "security_id": self._integer(raw_leg.get("security_id")),
            "ltp": self._number(raw_leg.get("last_price")),
            "previous_close": self._number(raw_leg.get("previous_close_price")),
            "oi": self._integer(raw_leg.get("oi")),
            "previous_oi": self._integer(raw_leg.get("previous_oi")),
            "volume": self._integer(raw_leg.get("volume")),
            "previous_volume": self._integer(raw_leg.get("previous_volume")),
            "average_price": self._number(raw_leg.get("average_price")),
            "iv": self._number(raw_leg.get("implied_volatility")),
            "delta": self._number(greeks.get("delta")),
            "gamma": self._number(greeks.get("gamma")),
            "theta": self._number(greeks.get("theta")),
            "vega": self._number(greeks.get("vega")),
            "top_ask_price": self._number(raw_leg.get("top_ask_price")),
            "top_ask_quantity": self._integer(raw_leg.get("top_ask_quantity")),
            "top_bid_price": self._number(raw_leg.get("top_bid_price")),
            "top_bid_quantity": self._integer(raw_leg.get("top_bid_quantity")),
        }
        for field_name in ("ltp", "previous_close", "oi", "previous_oi", "volume", "iv"):
            if values[field_name] is None:
                missing_fields.add(f"{strike:g}.{option_type.lower()}.{field_name}")
        return values

    def _build_leg(self, values, option_type, baseline):
        ltp = values["ltp"]
        oi = values["oi"]
        previous_close = values["previous_close"]
        previous_oi = values["previous_oi"]
        baseline_ltp = baseline.get("baseline_ltp") if baseline else None
        baseline_oi = baseline.get("baseline_oi") if baseline else None

        day_price_change = self._difference(ltp, previous_close, precision=4)
        day_change_oi = self._integer_difference(oi, previous_oi)
        intraday_price_change = self._difference(ltp, baseline_ltp, precision=4)
        intraday_change_oi = self._integer_difference(oi, baseline_oi)
        day_positioning = self._positioning(day_price_change, day_change_oi)
        positioning = self._positioning(
            intraday_price_change, intraday_change_oi
        )

        return OptionLegSnapshot(
            security_id=values["security_id"],
            ltp=ltp,
            previous_close=previous_close,
            price_change=day_price_change,
            day_price_change=day_price_change,
            intraday_price_change=intraday_price_change,
            oi=oi,
            previous_oi=previous_oi,
            change_oi=day_change_oi,
            day_change_oi=day_change_oi,
            intraday_change_oi=intraday_change_oi,
            baseline_oi=baseline_oi,
            baseline_ltp=baseline_ltp,
            volume=values["volume"],
            previous_volume=values.get("previous_volume"),
            average_price=values.get("average_price"),
            iv=values["iv"],
            delta=values.get("delta"),
            gamma=values.get("gamma"),
            theta=values.get("theta"),
            vega=values.get("vega"),
            top_ask_price=values["top_ask_price"],
            top_ask_quantity=values["top_ask_quantity"],
            top_bid_price=values["top_bid_price"],
            top_bid_quantity=values["top_bid_quantity"],
            change_oi_basis="previous_day",
            intraday_change_oi_basis="session_baseline",
            day_positioning=day_positioning,
            day_activity=self._activity(option_type, day_positioning),
            positioning=positioning,
            activity=self._activity(option_type, positioning),
        )

    @classmethod
    def _positioning(cls, price_change, change_oi):
        if price_change is None or change_oi is None:
            return "INSUFFICIENT_DATA"
        if (
            abs(price_change) < cls.MIN_PRICE_CHANGE
            or abs(change_oi) < cls.MIN_OI_CHANGE
        ):
            return "NEUTRAL"
        if price_change > 0 and change_oi > 0:
            return "LONG_BUILDUP"
        if price_change < 0 and change_oi > 0:
            return "SHORT_BUILDUP"
        if price_change > 0 and change_oi < 0:
            return "SHORT_COVERING"
        if price_change < 0 and change_oi < 0:
            return "LONG_UNWINDING"
        return "NEUTRAL"

    @staticmethod
    def _activity(option_type, positioning):
        labels = {
            ("CE", "SHORT_BUILDUP"): "CALL_WRITING",
            ("CE", "SHORT_COVERING"): "CALL_SHORT_COVERING",
            ("CE", "LONG_BUILDUP"): "CALL_BUYING",
            ("CE", "LONG_UNWINDING"): "CALL_LONG_UNWINDING",
            ("PE", "SHORT_BUILDUP"): "PUT_WRITING",
            ("PE", "SHORT_COVERING"): "PUT_SHORT_COVERING",
            ("PE", "LONG_BUILDUP"): "PUT_BUYING",
            ("PE", "LONG_UNWINDING"): "PUT_LONG_UNWINDING",
        }
        return labels.get((option_type, positioning), positioning)

    @staticmethod
    def _moneyness(option_type, strike, atm_strike):
        if strike == atm_strike:
            return "ATM"
        if option_type == "CE":
            return "ITM" if strike < atm_strike else "OTM"
        return "ITM" if strike > atm_strike else "OTM"

    @staticmethod
    def _strike_windows(strikes, atm_strike):
        below = [strike for strike in strikes if strike < atm_strike]
        above = [strike for strike in strikes if strike > atm_strike]
        lower_five = below[-5:]
        upper_five = above[:5]
        return {
            "ce_itm": lower_five,
            "ce_otm": upper_five,
            "pe_itm": upper_five,
            "pe_otm": lower_five,
        }

    @classmethod
    def _totals(cls, strikes):
        ce_oi = cls._sum_available(strikes, "ce", "oi") or 0
        pe_oi = cls._sum_available(strikes, "pe", "oi") or 0
        day_ce = cls._sum_available(strikes, "ce", "day_change_oi") or 0
        day_pe = cls._sum_available(strikes, "pe", "day_change_oi") or 0
        intraday_ce = cls._sum_available(strikes, "ce", "intraday_change_oi")
        intraday_pe = cls._sum_available(strikes, "pe", "intraday_change_oi")
        return OptionChainTotals(
            ce_oi=ce_oi,
            pe_oi=pe_oi,
            ce_change_oi=day_ce,
            pe_change_oi=day_pe,
            day_ce_change_oi=day_ce,
            day_pe_change_oi=day_pe,
            intraday_ce_change_oi=intraday_ce,
            intraday_pe_change_oi=intraday_pe,
            pcr=cls._ratio(pe_oi, ce_oi),
            change_pcr=cls._ratio(day_pe, day_ce),
            day_change_pcr=cls._ratio(day_pe, day_ce),
            intraday_change_pcr=cls._ratio(intraday_pe, intraday_ce),
        )

    @classmethod
    def _walls(cls, strikes):
        return OptionChainWalls(
            highest_ce_oi=cls._highest_level(strikes, "ce", "oi"),
            highest_pe_oi=cls._highest_level(strikes, "pe", "oi"),
            highest_ce_change_oi=cls._highest_level(
                strikes, "ce", "day_change_oi"
            ),
            highest_pe_change_oi=cls._highest_level(
                strikes, "pe", "day_change_oi"
            ),
            highest_intraday_ce_oi_addition=cls._highest_positive_level(
                strikes, "ce", "intraday_change_oi"
            ),
            highest_intraday_pe_oi_addition=cls._highest_positive_level(
                strikes, "pe", "intraday_change_oi"
            ),
            strongest_ce_unwind=cls._lowest_negative_level(
                strikes, "ce", "intraday_change_oi"
            ),
            strongest_pe_unwind=cls._lowest_negative_level(
                strikes, "pe", "intraday_change_oi"
            ),
        )

    @classmethod
    def _dominance(cls, window):
        raw = {
            "call_writing": 0,
            "put_writing": 0,
            "call_buying": 0,
            "put_buying": 0,
        }
        classified = 0
        for strike in window:
            for leg in (strike.ce, strike.pe):
                if leg.positioning not in ("NEUTRAL", "INSUFFICIENT_DATA"):
                    classified += 1
            if strike.ce.activity == "CALL_WRITING":
                raw["call_writing"] += max(strike.ce.intraday_change_oi or 0, 0)
            if strike.pe.activity == "PUT_WRITING":
                raw["put_writing"] += max(strike.pe.intraday_change_oi or 0, 0)
            if strike.ce.activity == "CALL_BUYING":
                raw["call_buying"] += max(strike.ce.intraday_change_oi or 0, 0)
            if strike.pe.activity == "PUT_BUYING":
                raw["put_buying"] += max(strike.pe.intraday_change_oi or 0, 0)

        core_total = sum(raw.values())
        writers = raw["call_writing"] + raw["put_writing"]
        buyers = raw["call_buying"] + raw["put_buying"]
        denominator = writers + buyers

        def score(value):
            return round(value / core_total * 100, 2) if core_total else 0.0

        dominance = ArgusDominance(
            call_writing_score=score(raw["call_writing"]),
            put_writing_score=score(raw["put_writing"]),
            call_buying_score=score(raw["call_buying"]),
            put_buying_score=score(raw["put_buying"]),
            writer_dominance_percentage=(
                round(writers / denominator * 100, 2) if denominator else 0.0
            ),
            buyer_dominance_percentage=(
                round(buyers / denominator * 100, 2) if denominator else 0.0
            ),
            evidence_coverage_percentage=(
                round(classified / (len(window) * 2) * 100, 2)
                if window
                else 0.0
            ),
            formula=(
                "Each score is its positive intraday OI addition divided by total "
                "ATM±5 writing/buying OI additions; writer/buyer dominance uses "
                "their respective grouped additions."
            ),
        )
        return dominance, raw

    @classmethod
    def _verdict(cls, dominance, raw_scores, walls, baseline_timestamp):
        call_wall = walls.highest_ce_oi
        put_wall = walls.highest_pe_oi
        breakout = call_wall.strike if call_wall else None
        breakdown = put_wall.strike if put_wall else None
        avoid_zone = (
            {"lower": min(breakout, breakdown), "upper": max(breakout, breakdown)}
            if breakout is not None and breakdown is not None
            else None
        )
        core_total = sum(raw_scores.values())
        reasons = []

        if baseline_timestamp is None or core_total == 0:
            if baseline_timestamp is None:
                reasons.append("No valid session baseline is available.")
            if core_total == 0:
                reasons.append("ATM ±5 has no qualifying writing or buying OI addition.")
            return ArgusVerdict(
                regime="INSUFFICIENT_DATA",
                bias="NEUTRAL",
                preferred_option_side="NONE",
                confidence=0,
                reasons=reasons,
                call_wall=call_wall,
                put_wall=put_wall,
                breakout_above=breakout,
                breakdown_below=breakdown,
                avoid_zone=avoid_zone,
                confidence_formula=cls._confidence_formula(),
            )

        writer_share = dominance.writer_dominance_percentage
        buyer_share = dominance.buyer_dominance_percentage
        if writer_share >= 60:
            regime = "WRITER_DOMINATED"
        elif buyer_share >= 60:
            regime = "BUYER_DOMINATED"
        else:
            regime = "MIXED"

        bullish = raw_scores["put_writing"] + raw_scores["call_buying"]
        bearish = raw_scores["call_writing"] + raw_scores["put_buying"]
        directional_total = bullish + bearish
        bullish_share = bullish / directional_total * 100 if directional_total else 0
        bearish_share = bearish / directional_total * 100 if directional_total else 0

        if bullish_share >= 60:
            bias = "BULLISH"
            preferred = "CE"
        elif bearish_share >= 60:
            bias = "BEARISH"
            preferred = "PE"
        elif regime == "WRITER_DOMINATED":
            bias = "RANGE_BOUND"
            preferred = "NONE"
        else:
            bias = "NEUTRAL"
            preferred = "NONE"

        dominance_strength = max(writer_share, buyer_share)
        directional_strength = abs(bullish_share - bearish_share)
        confidence = round(
            dominance.evidence_coverage_percentage
            * (0.6 * dominance_strength + 0.4 * directional_strength)
            / 100
        )
        confidence = max(0, min(100, confidence))
        reasons.extend(
            [
                f"ATM ±5 writer dominance is {writer_share:.2f}% and buyer dominance is {buyer_share:.2f}%.",
                f"Bullish evidence OI is {bullish} versus bearish evidence OI {bearish}.",
                f"Classified evidence coverage is {dominance.evidence_coverage_percentage:.2f}%.",
            ]
        )
        if call_wall:
            reasons.append(
                f"Highest call OI is {call_wall.value} at {call_wall.strike:g}."
            )
        if put_wall:
            reasons.append(
                f"Highest put OI is {put_wall.value} at {put_wall.strike:g}."
            )

        return ArgusVerdict(
            regime=regime,
            bias=bias,
            preferred_option_side=preferred,
            confidence=confidence,
            reasons=reasons,
            call_wall=call_wall,
            put_wall=put_wall,
            breakout_above=breakout,
            breakdown_below=breakdown,
            avoid_zone=avoid_zone,
            confidence_formula=cls._confidence_formula(),
        )

    @staticmethod
    def _confidence_formula():
        return (
            "round(evidence_coverage% × (0.6 × max(writer%, buyer%) + "
            "0.4 × abs(bullish%, bearish% spread)) / 100), bounded 0–100"
        )

    @staticmethod
    def _sum_available(strikes, leg_name, field_name):
        values = [
            getattr(getattr(strike, leg_name), field_name)
            for strike in strikes
            if getattr(getattr(strike, leg_name), field_name) is not None
        ]
        return sum(values) if values else None

    @staticmethod
    def _highest_level(strikes, leg_name, field_name):
        available = [
            (strike.strike, getattr(getattr(strike, leg_name), field_name))
            for strike in strikes
            if getattr(getattr(strike, leg_name), field_name) is not None
        ]
        if not available:
            return None
        strike, value = max(available, key=lambda item: item[1])
        return OptionChainLevel(strike=strike, value=value)

    @classmethod
    def _highest_positive_level(cls, strikes, leg_name, field_name):
        level = cls._highest_level(strikes, leg_name, field_name)
        return level if level is not None and level.value > 0 else None

    @staticmethod
    def _lowest_negative_level(strikes, leg_name, field_name):
        available = [
            (strike.strike, getattr(getattr(strike, leg_name), field_name))
            for strike in strikes
            if getattr(getattr(strike, leg_name), field_name) is not None
            and getattr(getattr(strike, leg_name), field_name) < 0
        ]
        if not available:
            return None
        strike, value = min(available, key=lambda item: item[1])
        return OptionChainLevel(strike=strike, value=value)

    @staticmethod
    def _ratio(numerator, denominator):
        if denominator in (None, 0) or numerator is None:
            return None
        return round(numerator / denominator, 4)

    @staticmethod
    def _difference(current, baseline, precision):
        if current is None or baseline is None:
            return None
        return round(current - baseline, precision)

    @staticmethod
    def _integer_difference(current, baseline):
        if current is None or baseline is None:
            return None
        return int(current) - int(baseline)

    def _now(self):
        value = self.now_provider()
        if value.tzinfo is None:
            return value.replace(tzinfo=self.EXCHANGE_TIMEZONE)
        return value.astimezone(self.EXCHANGE_TIMEZONE)

    @staticmethod
    def _number(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _raise_for_dhan_error(response, label):
        if not isinstance(response, dict):
            raise OptionChainDataError(f"Dhan {label} returned an invalid response")
        data = response.get("data")
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str) and ("too many requests" in v.lower() or "blocked" in v.lower()):
                    raise OptionChainDataError(f"Dhan {label} rate limited: {v}")
        error = (
            response.get("errorMessage")
            or response.get("error")
            or response.get("remarks")
        )
        if error:
            raise OptionChainDataError(f"Dhan {label} failed: {error}")
