# CitadelOS Project Roadmap

## Sprint 1 — Foundation
Status: Completed

- Mac setup
- VS Code setup
- Python setup
- Git setup
- Project structure
- Dhan API handshake

## Sprint 2 — Broker Layer
Goal: Make Dhan integration production-ready.

Modules:
- Dhan Connector
- Fund Limits
- Holdings
- Positions
- Orders
- Token expiry handling
- Broker health check

## Sprint 3 — Market Data Engine
Goal: Bring clean market data into CitadelOS.

Modules:
- Quotes
- Historical candles
- Live candles
- Instrument master
- Timeframe conversion
- Data validation

## Sprint 4 — Strategy Engine
Goal: Convert Pullback V3 into clean rule-based strategy.

Modules:
- Signal generator
- EMA
- VWAP
- RSI
- Supertrend
- Filters
- No-trade conditions

## Sprint 5 — Risk Engine
Goal: Protect capital before execution.

Modules:
- Daily loss limit
- Per-trade risk
- Quantity calculator
- Max trades per day
- Volatility block
- Kill switch

## Sprint 6 — Execution Engine
Goal: Place, manage, and exit trades safely.

Modules:
- Place order
- Modify order
- Cancel order
- Exit position
- Stop loss
- Target
- Trailing logic

## Sprint 7 — Paper Trading
Goal: Test complete system without real money.

Modules:
- Simulated orders
- Paper P&L
- Slippage model
- Trade journal
- Replay mode

## Sprint 8 — Kronos AI Engine
Goal: Add time-series AI confirmation.

Modules:
- Kronos model loading
- Candle feature preparation
- AI confidence score
- Trend probability
- Reversal risk
- Signal filter

## Sprint 9 — OpenAI Reasoning Layer
Goal: Add market reasoning and news intelligence.

Modules:
- News summarization
- Event impact
- Market explanation
- Trade reasoning
- AI report generation

## Sprint 10 — Memory Engine
Goal: Make CitadelOS learn from every trade.

Modules:
- Trade memory
- Mistake tagging
- Pattern tracking
- Performance by time slot
- Performance by market condition
- AI feedback loop

## Sprint 11 — Dashboard
Goal: Build visual control center.

Modules:
- Live P&L
- Positions
- Risk status
- AI confidence
- Trade journal
- Health monitor

## Sprint 12 — Live Trading
Goal: Controlled real capital deployment.

Modules:
- Live mode
- Strict risk rules
- Kill switch
- Audit logs
- Post-trade analytics