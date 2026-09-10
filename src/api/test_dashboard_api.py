from src.api.dashboard_api import DashboardAPI


api = DashboardAPI()
data = api.snapshot()

print("=" * 80)
print("CITADEL DASHBOARD API TEST")
print("=" * 80)

print()
print("STATUS")
print(data["status"])

print()
print("SCANNER ROWS:", len(data["scanner"]))
for row in data["scanner"][:3]:
    print({
        "symbol": row.get("symbol"),
        "ltp": row.get("ltp"),
        "bias": row.get("bias"),
        "confidence": row.get("confidence"),
        "signal": row.get("pullback_signal"),
        "entry": row.get("entry"),
        "sl": row.get("sl"),
        "target": row.get("target"),
    })

print()
print("ACTIVE TRADE")
print(data["active_trade"])

print()
print("JOURNAL SUMMARY")
print(data["journal_summary"])

print()
print("ANALYTICS SUMMARY")
print(data["analytics"]["summary"])

print()
print("OPTIMIZER SUGGESTIONS")
for s in data["optimizer"]["suggestions"]:
    print(s)