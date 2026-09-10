"""Strategy Registry for CITADEL Personal Strategy Layer."""

from typing import Dict, List, Optional
from src.eye.personal_strategies.contracts import (
    PersonalStrategyId,
    PersonalStrategyMetadata,
    ValidationStatus,
    DeploymentStatus,
)


class PersonalStrategyRegistry:
    """Registry maintaining metadata & status of user strategies."""

    _instance: Optional["PersonalStrategyRegistry"] = None

    @classmethod
    def get_instance(cls) -> "PersonalStrategyRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.strategies: Dict[str, PersonalStrategyMetadata] = {}
        self._register_approved_strategies()

    def _register_approved_strategies(self):
        # S01
        self.strategies[PersonalStrategyId.S01] = PersonalStrategyMetadata(
            strategy_id=PersonalStrategyId.S01,
            canonical_name="OTM1 CE PREMIUM BB–RSI MOMENTUM BREAKOUT",
            short_label="BB–RSI MOMENTUM",
            version="1.0",
            status="ACTIVE",
            validation_status=ValidationStatus.BACKTEST_REQUIRED,
            deployment_status=DeploymentStatus.DETECTION_ONLY,
            direction="BULLISH",
            underlying="NIFTY",
            instrument="OPT",
            expiry_rule="CURRENT_WEEK",
            contract_rule="OTM1_CE",
            quantity_rule="1_LOT",
            required_timeframes=["3m"],
        )

        # S02
        self.strategies[PersonalStrategyId.S02] = PersonalStrategyMetadata(
            strategy_id=PersonalStrategyId.S02,
            canonical_name="NIFTY VOLATILE",
            short_label="NIFTY VOLATILE",
            version="1.0",
            status="ACTIVE",
            validation_status=ValidationStatus.BACKTEST_REQUIRED,
            deployment_status=DeploymentStatus.DETECTION_ONLY,
            direction="BOTH",
            underlying="NIFTY",
            instrument="OPT",
            expiry_rule="CURRENT_WEEK",
            contract_rule="NEAREST_200_PREMIUM",
            quantity_rule="STAGED",
            required_timeframes=["5m", "15m", "1D"],
        )

        # S03
        self.strategies[PersonalStrategyId.S03] = PersonalStrategyMetadata(
            strategy_id=PersonalStrategyId.S03,
            canonical_name="NIFTY TREND CATCHER",
            short_label="TREND CATCHER",
            version="1.0",
            status="ACTIVE",
            validation_status=ValidationStatus.BACKTEST_REQUIRED,
            deployment_status=DeploymentStatus.DETECTION_ONLY,
            direction="BEARISH",
            underlying="NIFTY",
            instrument="OPT",
            expiry_rule="1_DTE_WEEKLY",
            contract_rule="OTM2_PE",
            quantity_rule="1_LOT",
            required_timeframes=["1m", "5m"],
        )

        # S04
        self.strategies[PersonalStrategyId.S04] = PersonalStrategyMetadata(
            strategy_id=PersonalStrategyId.S04,
            canonical_name="NIFTY BULL PULSE",
            short_label="BULL PULSE",
            version="1.0",
            status="ACTIVE",
            validation_status=ValidationStatus.BACKTEST_REQUIRED,
            deployment_status=DeploymentStatus.DETECTION_ONLY,
            direction="BULLISH",
            underlying="NIFTY",
            instrument="OPT",
            expiry_rule="4_DTE_WEEKLY",
            contract_rule="OTM2_CE",
            quantity_rule="1_LOT",
            required_timeframes=["1m", "5m"],
        )

        # S05
        self.strategies[PersonalStrategyId.S05] = PersonalStrategyMetadata(
            strategy_id=PersonalStrategyId.S05,
            canonical_name="OTM1 OPTION PREMIUM BB–CPR BREAKOUT",
            short_label="BB–CPR BREAKOUT",
            version="1.0",
            status="ACTIVE",
            validation_status=ValidationStatus.BACKTEST_REQUIRED,
            deployment_status=DeploymentStatus.DETECTION_ONLY,
            direction="BOTH",
            underlying="NIFTY",
            instrument="OPT",
            expiry_rule="CURRENT_WEEK",
            contract_rule="OTM1",
            quantity_rule="1_LOT",
            required_timeframes=["3m", "5m", "1D"],
        )

        # S06
        self.strategies[PersonalStrategyId.S06] = PersonalStrategyMetadata(
            strategy_id=PersonalStrategyId.S06,
            canonical_name="OPENING PREMIUM MOMENTUM RECOVERY v1.2",
            short_label="OPENING MOMENTUM RECOVERY",
            version="1.2",
            status="ACTIVE",
            validation_status=ValidationStatus.BACKTEST_REQUIRED,
            deployment_status=DeploymentStatus.DETECTION_ONLY,
            direction="BOTH",
            underlying="NIFTY",
            instrument="OPT",
            expiry_rule="CURRENT_WEEK",
            contract_rule="DELTA_045_ATM_OTM1",
            quantity_rule="ADAPTIVE_RISK",
            required_timeframes=["1m", "3m"],
        )

        # S07 - PARKED NOT AUTHORIZED
        self.strategies[PersonalStrategyId.S07] = PersonalStrategyMetadata(
            strategy_id=PersonalStrategyId.S07,
            canonical_name="CITADEL VWAP INITIATIVE PULLBACK — V2",
            short_label="VWAP INITIATIVE",
            version="2.0",
            status="PARKED_NOT_AUTHORIZED",
            validation_status=ValidationStatus.BACKTEST_REQUIRED,
            deployment_status=DeploymentStatus.PARKED_NOT_AUTHORIZED,
            direction="BOTH",
            underlying="NIFTY",
            instrument="OPT",
            expiry_rule="CURRENT_WEEK",
            contract_rule="UNREGISTERED",
            quantity_rule="UNREGISTERED",
            required_timeframes=[],
        )

    def get_strategy_metadata(self, strategy_id: str) -> Optional[PersonalStrategyMetadata]:
        return self.strategies.get(strategy_id)

    def get_enabled_strategies(self) -> List[PersonalStrategyMetadata]:
        return [s for s in self.strategies.values() if s.status == "ACTIVE"]
