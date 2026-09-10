# Stage 9 — Broker Layer

## Objective

Build a clean, production-ready broker connector for Dhan.

This stage is only about broker communication.

No strategy logic.
No AI logic.
No order placement yet.

---

## Current Status

Dhan REST API handshake is successful.

Working endpoint tested:

GET https://api.dhan.co/v2/fundlimit

Result:

Status Code 200

---

## Decision

Use direct REST API with `requests`.

Do not use `dhanhq` SDK for now because SDK compatibility issues were found.

---

## Files To Create

src/broker/dhan_connector.py

---

## Class

DhanConnector

---

## Responsibilities

1. Load access token from `config/.env`
2. Create common request method
3. Handle API errors
4. Hide credentials from logs
5. Provide clean methods for broker data

---

## Required Methods

- get_fund_limits()
- get_holdings()
- get_positions()
- get_orders()

---

## Common Request Method

_request(method, endpoint, payload=None, params=None)

Base URL:

https://api.dhan.co/v2

Headers:

access-token
Content-Type: application/json

---

## Error Handling

Handle:

- Missing access token
- Expired token
- Invalid token
- Network failure
- Non-200 response
- JSON parsing failure

---

## Test Command

python src/dhan_client.py

---

## Success Criteria

1. App loads token safely.
2. Fund limits return status code 200.
3. No token appears in logs.
4. Errors are readable.
5. Code is reusable for future stages.