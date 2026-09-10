# CitadelOS Architecture

## Vision

CitadelOS is an AI-native algorithmic trading operating system.

It is NOT a trading strategy.

It is NOT a broker wrapper.

It is the operating system that coordinates every component involved in quantitative trading.

---

# High Level Architecture

                +----------------------+
                |   OpenAI Finance     |
                +----------+-----------+
                           |
                           |
                +----------v-----------+
                |      Kronos AI       |
                +----------+-----------+
                           |
                           |
                 +---------v---------+
                 |  Strategy Engine  |
                 +---------+---------+
                           |
                 Risk Validation Engine
                           |
                 +---------v---------+
                 | Execution Engine  |
                 +---------+---------+
                           |
                 Broker Abstraction Layer
                           |
        +------------------+------------------+
        |                  |                  |
      Dhan             Zerodha           Interactive Brokers
        |                  |                  |
        +------------------+------------------+
                           |
                    Exchange APIs

-------------------------------------------------

Parallel Services

• Market Data Engine
• News Engine
• Logging Engine
• Portfolio Engine
• Journal Engine
• Alert Engine
• Backtest Engine
• Paper Trading Engine
• Monitoring Dashboard

-------------------------------------------------

Folder Responsibilities

config/
Application configuration

src/
Business logic

brokers/
Broker connectors only

strategies/
Trading logic only

risk/
Risk engine

market/
Market data

portfolio/
Positions

journal/
Trade history

logs/
Application logs

tests/
Testing

docs/
Architecture and documentation

-------------------------------------------------

Core Principle

Strategies never know which broker exists.

Execution Engine never knows how a strategy works.

Broker never knows how AI thinks.

AI never sends orders directly.

Every layer has only one responsibility.

-------------------------------------------------

Execution Flow

Market Data

↓

Strategy Signal

↓

Risk Validation

↓

Position Sizing

↓

Execution Engine

↓

Broker

↓

Exchange

↓

Trade Confirmation

↓

Journal

↓

Portfolio

↓

Monitoring Dashboard

-------------------------------------------------

Future AI Modules

Kronos
Market reasoning

OpenAI Finance
Research

Sentinel
Risk intelligence

Oracle
Portfolio optimization

Atlas
Macro intelligence

-------------------------------------------------

Security Rules

No credentials in source code.

Secrets only inside .env.

Every API call logged.

Every exception logged.

Every order auditable.

Paper trading before live trading.

Kill switch mandatory.

-------------------------------------------------

End Goal

CitadelOS should become a plug-and-play institutional trading operating system capable of running multiple AI models, multiple brokers, multiple exchanges and multiple strategies simultaneously.