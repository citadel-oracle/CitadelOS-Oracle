from src.eye.position.intent import ExecutionIntentService


def test_execution_intent_is_idempotent_and_never_live(tmp_path):
    service = ExecutionIntentService(tmp_path)
    one = service.create(strategy_id="S02", cycle_id="C1", security_id="42", side="BUY", quantity=50, entry_policy="MARKET", timestamp=1.0, reason="TEST", protective_risk={"sl": 15})
    two = service.create(strategy_id="S02", cycle_id="C1", security_id="42", side="BUY", quantity=50, entry_policy="MARKET", timestamp=1.0, reason="TEST", protective_risk={"sl": 15})
    assert one.intent_id == two.intent_id
    assert len(service.list()) == 1
