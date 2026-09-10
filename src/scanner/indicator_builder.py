"""
CitadelOS Indicator Builder V2
EMA, RSI, ATR, VWAP, ADX, SMA, Highest High, Lowest Low.
"""

import math
from datetime import datetime, time
from zoneinfo import ZoneInfo


class IndicatorBuilder:
    EMA_PERIODS = (21, 38)
    SMA_PERIOD = 20
    RSI_PERIOD = 14
    ATR_PERIOD = 14
    ADX_PERIOD = 14
    RANGE_PERIOD = 20
    EXCHANGE_TIMEZONE = ZoneInfo("Asia/Kolkata")
    SESSION_OPEN = time(9, 15)
    SESSION_CLOSE = time(15, 30)

    @property
    def required_candle_count(self):
        """Minimum derived from the periods used by the implemented formulas."""

        return max(
            max(self.EMA_PERIODS),
            self.SMA_PERIOD,
            self.RSI_PERIOD + 1,
            self.ATR_PERIOD + 1,
            self.ADX_PERIOD + 2,
            self.RANGE_PERIOD,
        )

    def build(self, candles, *, session_date=None):
        rows = self._valid_rows(candles)
        closes = self._series(rows, "close")
        highs = self._series(rows, "high")
        lows = self._series(rows, "low")

        if len(closes) < self.required_candle_count:
            return self._empty(closes)

        session_rows = self._session_rows(rows, session_date)
        session_highs = self._series(session_rows, "high")
        session_lows = self._series(session_rows, "low")
        session_closes = self._series(session_rows, "close")
        session_volumes = self._series(session_rows, "volume", allow_zero=True)

        return {
            "close": closes[-1],
            "ema_21": self._ema(closes, self.EMA_PERIODS[0]),
            "ema_38": self._ema(closes, self.EMA_PERIODS[1]),
            "sma_20": self._sma(closes, self.SMA_PERIOD),
            "rsi_14": self._rsi(closes, self.RSI_PERIOD),
            "atr_14": self._atr(highs, lows, closes, self.ATR_PERIOD),
            "adx_14": self._adx(highs, lows, closes, self.ADX_PERIOD),
            "vwap": self._vwap(
                session_highs,
                session_lows,
                session_closes,
                session_volumes,
            ),
            "highest_20": max(highs[-self.RANGE_PERIOD:]) if len(highs) >= self.RANGE_PERIOD else None,
            "lowest_20": min(lows[-self.RANGE_PERIOD:]) if len(lows) >= self.RANGE_PERIOD else None,
        }

    def _empty(self, closes):
        return {
            "close": closes[-1] if closes else None,
            "ema_21": None,
            "ema_38": None,
            "sma_20": None,
            "rsi_14": None,
            "atr_14": None,
            "adx_14": None,
            "vwap": None,
            "highest_20": None,
            "lowest_20": None,
        }

    def _series(self, candles, key, allow_zero=False):
        values = []
        for c in candles:
            try:
                value = float(c.get(key, 0))
                if value > 0 or allow_zero:
                    values.append(value)
            except Exception:
                pass
        return values

    @staticmethod
    def _valid_rows(candles):
        rows = []
        for source in candles:
            try:
                values = {
                    key: float(source[key])
                    for key in ("open", "high", "low", "close")
                }
                if not all(
                    math.isfinite(value) and value > 0
                    for value in values.values()
                ):
                    continue
                if (
                    values["high"] < max(values.values())
                    or values["low"] > min(values.values())
                ):
                    continue
                rows.append(source)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return rows

    def _session_rows(self, candles, session_date):
        if session_date is None:
            return list(candles)
        rows = []
        for candle in candles:
            try:
                timestamp = candle["time"]
                if isinstance(timestamp, datetime):
                    observed = timestamp
                elif isinstance(timestamp, (int, float)):
                    value = float(timestamp)
                    if value > 10_000_000_000:
                        value /= 1000
                    observed = datetime.fromtimestamp(
                        value, tz=self.EXCHANGE_TIMEZONE
                    )
                else:
                    observed = datetime.fromisoformat(
                        str(timestamp).replace("Z", "+00:00")
                    )
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=self.EXCHANGE_TIMEZONE)
                else:
                    observed = observed.astimezone(self.EXCHANGE_TIMEZONE)
                if (
                    observed.date() == session_date
                    and self.SESSION_OPEN <= observed.time() < self.SESSION_CLOSE
                ):
                    rows.append(candle)
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
        return rows

    def _sma(self, values, length):
        if len(values) < length:
            return None
        return round(sum(values[-length:]) / length, 2)

    def _ema(self, values, length):
        if len(values) < length:
            return None
        k = 2 / (length + 1)
        # Match the canonical TradingView/Pine recursive EMA over the complete
        # supplied history.  Truncating to the final `length` observations
        # materially changes the live result.
        ema = values[0]
        for price in values[1:]:
            ema = price * k + ema * (1 - k)
        return round(ema, 2)

    def _rsi(self, values, length):
        if len(values) < length + 1:
            return None

        gains = []
        losses = []

        for i in range(1, len(values)):
            change = values[i] - values[i - 1]
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))

        avg_gain = self._rma(gains, length)
        avg_loss = self._rma(losses, length)

        if avg_gain == 0 and avg_loss == 0:
            return 50
        if avg_loss == 0:
            return 100

        rs = avg_gain / avg_loss
        return round(100 - (100 / (1 + rs)), 2)

    def _atr(self, highs, lows, closes, length):
        if len(closes) < length + 1:
            return None

        trs = []

        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            trs.append(tr)

        return round(self._rma(trs, length), 2)

    def _adx(self, highs, lows, closes, length):
        if len(closes) < length + 2:
            return None

        plus_dm = []
        minus_dm = []
        tr_list = []

        for i in range(1, len(closes)):
            up_move = highs[i] - highs[i - 1]
            down_move = lows[i - 1] - lows[i]

            plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
            minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_list.append(tr)

        if len(tr_list) < length * 2 - 1:
            return None

        smoothed_tr = sum(tr_list[:length]) / length
        smoothed_plus = sum(plus_dm[:length]) / length
        smoothed_minus = sum(minus_dm[:length]) / length
        dx_values = []

        def dx_value(tr, plus, minus):
            if tr == 0:
                return 0.0
            plus_di = 100 * plus / tr
            minus_di = 100 * minus / tr
            total = plus_di + minus_di
            return 0.0 if total == 0 else abs(plus_di - minus_di) / total * 100

        dx_values.append(
            dx_value(smoothed_tr, smoothed_plus, smoothed_minus)
        )
        for index in range(length, len(tr_list)):
            smoothed_tr = (
                smoothed_tr * (length - 1) + tr_list[index]
            ) / length
            smoothed_plus = (
                smoothed_plus * (length - 1) + plus_dm[index]
            ) / length
            smoothed_minus = (
                smoothed_minus * (length - 1) + minus_dm[index]
            ) / length
            dx_values.append(
                dx_value(smoothed_tr, smoothed_plus, smoothed_minus)
            )

        return round(self._rma(dx_values, length), 2)

    def _vwap(self, highs, lows, closes, volumes):
        if not closes:
            return None

        total_pv = 0
        total_volume = 0

        if len(volumes) != len(closes):
            return None

        for h, l, c, v in zip(highs, lows, closes, volumes):
            if not math.isfinite(v) or v <= 0:
                return None
            typical_price = (h + l + c) / 3
            total_pv += typical_price * v
            total_volume += v

        if total_volume == 0:
            return None

        return round(total_pv / total_volume, 2)

    @staticmethod
    def _rma(values, length):
        """TradingView/Pine Wilder moving average."""

        if len(values) < length:
            return None
        average = sum(values[:length]) / length
        for value in values[length:]:
            average = (average * (length - 1) + value) / length
        return average
