from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict

from src.core.utils.date_utils import get_current_local_datetime
from src.logging.logger import get_application_logger

logger = get_application_logger(__name__)

from src.core.structures.structures import BlockchainNetwork


class PairIdentity(BaseModel):
    chain: BlockchainNetwork
    token_address: str
    pair_address: str

    def get_unique_key(self) -> str:
        strict_pair_or_token_address = self.pair_address if self.pair_address else self.token_address
        return f"{self.chain.value}:{strict_pair_or_token_address}".lower()


class WindowActivity(BaseModel):
    buys: Optional[int] = None
    sells: Optional[int] = None

    def get_total_transactions(self) -> Optional[int]:
        if self.buys is None or self.sells is None:
            return None
        return self.buys + self.sells


class Observation(BaseModel):
    observation_date: Optional[datetime] = None
    liquidity_usd: Optional[float] = None
    fully_diluted_valuation_usd: Optional[float] = None
    market_cap_usd: Optional[float] = None
    window_5m: Optional[WindowActivity] = None
    window_1h: Optional[WindowActivity] = None
    window_6h: Optional[WindowActivity] = None
    window_24h: Optional[WindowActivity] = None


class ConsistencyVerdict(Enum):
    OK = "OK"
    REQUIRES_MANUAL_INTERVENTION = "REQUIRES_MANUAL_INTERVENTION"


class StateRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    recent_fingerprints: list[str] = Field(default_factory=list)
    last_liquidity_usd: Optional[float] = None
    last_fully_diluted_valuation_usd: Optional[float] = None
    last_market_cap_usd: Optional[float] = None
    last_transactions_5m: Optional[int] = None
    last_transactions_1h: Optional[int] = None
    last_transactions_6h: Optional[int] = None
    last_transactions_24h: Optional[int] = None


class DexscreenerConsistencyGuard:
    def __init__(
            self,
            window_size: int,
            alternation_minimum_cycles: int,
            jump_factor: float,
            fields_mismatch_minimum: int,
            staleness_horizon: timedelta,
    ) -> None:
        self.window_size = max(2, window_size)
        self.alternation_minimum_cycles = max(1, alternation_minimum_cycles)
        self.jump_factor = max(1.0, jump_factor)
        self.fields_mismatch_minimum = max(1, fields_mismatch_minimum)
        self.staleness_horizon = staleness_horizon
        self.states_registry: dict[str, StateRecord] = {}

    @staticmethod
    def _compute_float_bucket(value: Optional[float], granularity: float) -> str:
        if value is None:
            return "UNAVAILABLE"
        if value <= 0.0:
            return "ZERO"
        safe_granularity = max(granularity, 1e-12)
        return f"{round(value / safe_granularity)}"

    @staticmethod
    def _compute_integer_bucket(value: Optional[int], divisor: int) -> str:
        if value is None:
            return "UNAVAILABLE"
        if value <= 0:
            return "ZERO"
        safe_divisor = max(divisor, 1)
        return f"{value // safe_divisor}"

    @staticmethod
    def _extract_total_transactions(window_activity: Optional[WindowActivity]) -> Optional[int]:
        if window_activity is None:
            return None
        return window_activity.get_total_transactions()

    def _generate_fingerprint(self, observation: Observation) -> str:
        liquidity_bucket = self._compute_float_bucket(value=observation.liquidity_usd, granularity=10.0)
        valuation_bucket = self._compute_float_bucket(value=observation.fully_diluted_valuation_usd, granularity=1000.0)
        market_cap_bucket = self._compute_float_bucket(value=observation.market_cap_usd, granularity=1000.0)

        transactions_5m_bucket = self._compute_integer_bucket(value=self._extract_total_transactions(window_activity=observation.window_5m), divisor=5)
        transactions_1h_bucket = self._compute_integer_bucket(value=self._extract_total_transactions(window_activity=observation.window_1h), divisor=10)
        transactions_6h_bucket = self._compute_integer_bucket(value=self._extract_total_transactions(window_activity=observation.window_6h), divisor=50)
        transactions_24h_bucket = self._compute_integer_bucket(value=self._extract_total_transactions(window_activity=observation.window_24h), divisor=200)

        return f"liquidity={liquidity_bucket}|valuation={valuation_bucket}|market_cap={market_cap_bucket}|transactions_5m={transactions_5m_bucket}|transactions_1h={transactions_1h_bucket}|transactions_6h={transactions_6h_bucket}|transactions_24h={transactions_24h_bucket}"

    @staticmethod
    def _detect_alternating_pattern(sequence: list[str], minimum_cycles: int) -> bool:
        needed_elements = 2 * minimum_cycles
        if len(sequence) < needed_elements:
            return False

        tail_elements = sequence[-needed_elements:]
        first_element = tail_elements[0]
        second_element = tail_elements[1]

        if first_element == second_element:
            return False

        for index, fingerprint in enumerate(tail_elements):
            expected_element = first_element if index % 2 == 0 else second_element
            if fingerprint != expected_element:
                return False

        return True

    @staticmethod
    def _has_value_jumped(current_value: Optional[float], previous_value: Optional[float], threshold_factor: float) -> bool:
        if current_value is None or previous_value is None:
            return False
        if current_value == 0.0 and previous_value == 0.0:
            return False
        if current_value == 0.0 or previous_value == 0.0:
            return True
        if current_value < 0.0 or previous_value < 0.0:
            return True

        ratio = current_value / previous_value
        return ratio >= threshold_factor or ratio <= (1.0 / threshold_factor)

    @staticmethod
    def _is_observation_stale(observation_date: Optional[datetime], staleness_horizon: timedelta) -> bool:
        if observation_date is None:
            return False
        try:
            return (get_current_local_datetime() - observation_date) > staleness_horizon
        except Exception as date_exception:
            logger.exception("[DEXSCREENER][CONSISTENCY][STALENESS] Failed to compute staleness duration with error: %s", date_exception)
            return False

    def _update_state_record(self, state_record: StateRecord, observation: Observation, fingerprint: str) -> None:
        state_record.recent_fingerprints.append(fingerprint)
        if len(state_record.recent_fingerprints) > self.window_size:
            state_record.recent_fingerprints = state_record.recent_fingerprints[-self.window_size:]

        state_record.last_liquidity_usd = observation.liquidity_usd
        state_record.last_fully_diluted_valuation_usd = observation.fully_diluted_valuation_usd
        state_record.last_market_cap_usd = observation.market_cap_usd
        state_record.last_transactions_5m = self._extract_total_transactions(window_activity=observation.window_5m)
        state_record.last_transactions_1h = self._extract_total_transactions(window_activity=observation.window_1h)
        state_record.last_transactions_6h = self._extract_total_transactions(window_activity=observation.window_6h)
        state_record.last_transactions_24h = self._extract_total_transactions(window_activity=observation.window_24h)

    def evaluate_consistency(self, pair_identity: PairIdentity, observation: Observation) -> ConsistencyVerdict:
        unique_key = pair_identity.get_unique_key()
        state_record = self.states_registry.get(unique_key)

        if state_record is None:
            state_record = StateRecord()
            self.states_registry[unique_key] = state_record

        if self._is_observation_stale(observation_date=observation.observation_date, staleness_horizon=self.staleness_horizon):
            logger.debug("[DEXSCREENER][CONSISTENCY][EVALUATION] Observation for key %s is too old, skipping jump evaluation", unique_key)
            fingerprint = self._generate_fingerprint(observation=observation)
            self._update_state_record(state_record=state_record, observation=observation, fingerprint=fingerprint)
            return ConsistencyVerdict.OK

        jumped_fields_count = 0
        ratios_log_entries: list[str] = []

        def evaluate_float_metric(metric_name: str, current_metric_value: Optional[float], previous_metric_value: Optional[float]) -> None:
            nonlocal jumped_fields_count
            if self._has_value_jumped(current_value=current_metric_value, previous_value=previous_metric_value, threshold_factor=self.jump_factor):
                jumped_fields_count += 1
                if current_metric_value is not None and previous_metric_value is not None and previous_metric_value > 0.0 and current_metric_value > 0.0:
                    ratios_log_entries.append(f"{metric_name}={current_metric_value / previous_metric_value:.4f}")
                else:
                    ratios_log_entries.append(f"{metric_name}=EDGE_CASE")

        def evaluate_integer_metric(metric_name: str, current_metric_value: Optional[int], previous_metric_value: Optional[int]) -> None:
            nonlocal jumped_fields_count
            current_float_value = float(current_metric_value) if current_metric_value is not None else None
            previous_float_value = float(previous_metric_value) if previous_metric_value is not None else None

            if self._has_value_jumped(current_value=current_float_value, previous_value=previous_float_value, threshold_factor=self.jump_factor):
                jumped_fields_count += 1
                if current_float_value is not None and previous_float_value is not None and previous_float_value > 0.0 and current_float_value > 0.0:
                    ratios_log_entries.append(f"{metric_name}={current_float_value / previous_float_value:.4f}")
                else:
                    ratios_log_entries.append(f"{metric_name}=EDGE_CASE")

        evaluate_float_metric(metric_name="liquidity", current_metric_value=observation.liquidity_usd, previous_metric_value=state_record.last_liquidity_usd)
        evaluate_float_metric(metric_name="fully_diluted_valuation", current_metric_value=observation.fully_diluted_valuation_usd, previous_metric_value=state_record.last_fully_diluted_valuation_usd)
        evaluate_float_metric(metric_name="market_cap", current_metric_value=observation.market_cap_usd, previous_metric_value=state_record.last_market_cap_usd)

        evaluate_integer_metric(metric_name="transactions_5m", current_metric_value=self._extract_total_transactions(window_activity=observation.window_5m), previous_metric_value=state_record.last_transactions_5m)
        evaluate_integer_metric(metric_name="transactions_1h", current_metric_value=self._extract_total_transactions(window_activity=observation.window_1h), previous_metric_value=state_record.last_transactions_1h)
        evaluate_integer_metric(metric_name="transactions_6h", current_metric_value=self._extract_total_transactions(window_activity=observation.window_6h), previous_metric_value=state_record.last_transactions_6h)
        evaluate_integer_metric(metric_name="transactions_24h", current_metric_value=self._extract_total_transactions(window_activity=observation.window_24h), previous_metric_value=state_record.last_transactions_24h)

        if jumped_fields_count >= self.fields_mismatch_minimum:
            logger.info(
                "[DEXSCREENER][CONSISTENCY][EVALUATION] Multiple jumps detected for key %s with %d fields out of 7. Ratios: [%s]. Verdict: REQUIRES_MANUAL_INTERVENTION",
                unique_key,
                jumped_fields_count,
                ", ".join(ratios_log_entries),
            )
            fingerprint = self._generate_fingerprint(observation=observation)
            self._update_state_record(state_record=state_record, observation=observation, fingerprint=fingerprint)
            return ConsistencyVerdict.REQUIRES_MANUAL_INTERVENTION

        fingerprint = self._generate_fingerprint(observation=observation)
        self._update_state_record(state_record=state_record, observation=observation, fingerprint=fingerprint)

        if self._detect_alternating_pattern(sequence=state_record.recent_fingerprints, minimum_cycles=self.alternation_minimum_cycles):
            logger.info("[DEXSCREENER][CONSISTENCY][EVALUATION] Alternating pattern detected for key %s. Verdict: REQUIRES_MANUAL_INTERVENTION", unique_key)
            return ConsistencyVerdict.REQUIRES_MANUAL_INTERVENTION

        return ConsistencyVerdict.OK
