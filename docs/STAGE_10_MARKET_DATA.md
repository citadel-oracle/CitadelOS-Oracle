# Stage 10 — Market Data Engine

## Objective

Build the Market Data Layer.

This layer becomes the single source of truth for every strategy.

No strategy should directly call Dhan.

-------------------------------------------------

Responsibilities

• Historical candles
• Live quotes
• Instrument lookup
• Market status
• Trading sessions
• Timeframe conversion
• Data validation

-------------------------------------------------

Input

Broker Layer

↓

Raw API Response

-------------------------------------------------

Output

Clean Data Objects

-------------------------------------------------

Files

src/market/

historical.py

quotes.py

instruments.py

market_clock.py

validator.py

-------------------------------------------------

Rules

Strategies never communicate with brokers.

Strategies only consume Market Engine.

-------------------------------------------------

Future

This layer should support

Dhan

Zerodha

Interactive Brokers

Polygon

Alpaca

without changing strategies.

-------------------------------------------------

Exit Criteria

Historical candles working.

Live quotes working.

Instrument lookup working.

Validated data returned.

No broker logic outside Market Engine.