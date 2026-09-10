# Dhan Broker Setup Guide

1. Provision a Dhan API application and data subscription.
2. Register the deployment host's static outbound IP.
3. Store the client ID and access token in the secret manager.
4. Validate the profile endpoint and token expiry without placing an order.
5. Validate instrument master, expiry list and option-chain access.
6. Establish the v2 full-packet WebSocket and confirm LTP, bid, ask and exchange timestamp decoding.
7. Test reconnect and stale-quote rejection.
8. Validate correlation-ID lookup, order status and position retrieval read-only.
9. Complete broker sandbox/UAT for place, modify, cancel, rejection and partial fill.
10. Obtain written approval before changing any LIVE gate.

Token refresh never writes credentials to application state or logs.
