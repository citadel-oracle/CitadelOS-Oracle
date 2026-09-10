# AI Trading Bible

## CitadelOS Core Principles

1. Strategy never places orders directly.
2. Every trade must pass through the Risk Engine.
3. Broker credentials must never be stored in source code.
4. Dhan is a broker plugin, not the core system.
5. Kronos/OpenAI are AI plugins, not the boss.
6. CitadelOS is the central operating system.
7. Every API response must be logged safely.
8. Every trade must be journaled.
9. No live trading before paper trading.
10. No automation without kill switch.

# Development Rules

## Rule 1
Never hardcode API credentials.

## Rule 2
Every module must have only one responsibility.

## Rule 3
No strategy may communicate directly with the broker.

## Rule 4
Every API call must return structured errors.

## Rule 5
Every exception must be logged.

## Rule 6
Every new feature must be modular.

## Rule 7
No AI model is irreplaceable.

## Rule 8
Every trade must be reproducible.

## Rule 9
Paper trading comes before live trading.

## Rule 10
No code reaches production without review.

# Memory Engine

## Purpose

Memory Engine ka kaam hai har trade, signal, mistake, win, loss aur market condition ko remember karna.

## Why Memory Engine Exists

Trading system sirf trade execute nahi karega.
System har trade se seekhega.

## Memory Engine Stores

1. Date and time
2. Symbol
3. Instrument
4. Strategy name
5. Entry reason
6. AI confidence
7. Risk score
8. Entry price
9. Stop loss
10. Target
11. Exit price
12. P&L
13. Mistake reason
14. Market condition
15. Screenshot or chart reference
16. Lesson learned

## Core Rule

Every trade must become data.

## Future Use

After enough trades, CitadelOS should be able to answer:

- Which setup works best?
- Which time slot is weakest?
- Which market condition should be avoided?
- Which strategy has hidden edge?
- Which losses were avoidable?
- Which AI confidence range performs best?

# Risk Engine Constitution

## Risk Philosophy

Capital protection comes before profit generation.

## Rules

### Rule 1
Maximum daily loss must be configurable.

### Rule 2
Maximum number of trades per day must be configurable.

### Rule 3
Position size must always be calculated before order placement.

### Rule 4
Risk per trade should be percentage-based, not emotion-based.

### Rule 5
If market volatility exceeds safe limits, trading can be blocked.

### Rule 6
Every rejected trade must include a reason.

### Rule 7
Risk Engine has authority to reject any strategy signal.

### Rule 8
Execution Engine can never bypass Risk Engine.

### Rule 9
Risk parameters must be loaded from config files.

### Rule 10
Emergency Kill Switch can disable all live trading instantly.

# Configuration Standards

## Rule 1
No secrets are allowed inside source code.

## Rule 2
Every configurable value must come from config files or environment variables.

## Rule 3
Hardcoded numbers are forbidden unless mathematically constant.

## Rule 4
Strategy settings must be independent from broker settings.

## Rule 5
Risk settings must be independent from strategy settings.

## Rule 6
Market settings must be independent from execution settings.

## Rule 7
Every configuration change must be logged.

## Rule 8
Production and Development configurations must remain separate.

## Rule 9
Missing configuration must stop the application safely.

## Rule 10
Configuration should be validated before startup.

# Logging Standards

## Every important event must be logged.

Logs should include:

- Startup
- Shutdown
- API Requests
- API Responses
- Errors
- Warnings
- Strategy Signals
- Risk Decisions
- Order Requests
- Order Executions
- Position Updates

## Never Log

- Access Tokens
- API Secrets
- Passwords

## Log Levels

INFO
WARNING
ERROR
DEBUG

Logs must be timestamped.