from __future__ import annotations

import random
import threading
import time

from src.configuration.config import settings
from src.integrations.blockchain.solana.solana_structures import (
    SolanaRpcEndpointRateLimitState,
    SolanaRpcFailureReason,
)


class SolanaRpcRateLimitStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._endpoint_states: list[SolanaRpcEndpointRateLimitState] = []

    def clear(self) -> None:
        with self._lock:
            self._endpoint_states.clear()

    def wait_before_rpc_request(self, rpc_url: str) -> None:
        maximum_requests_per_second = settings.SOLANA_RPC_MAX_REQUESTS_PER_SECOND
        minimum_spacing_seconds = 1.0 / float(maximum_requests_per_second)
        now_monotonic = time.monotonic()

        with self._lock:
            endpoint_state = self._resolve_endpoint_state(rpc_url)
            sleep_seconds = self._resolve_pre_request_sleep_seconds(
                endpoint_state=endpoint_state,
                now_monotonic=now_monotonic,
                minimum_spacing_seconds=minimum_spacing_seconds,
            )

        if sleep_seconds > 0.0:
            time.sleep(sleep_seconds)

        with self._lock:
            endpoint_state = self._resolve_endpoint_state(rpc_url)
            now_monotonic = time.monotonic()
            endpoint_state.request_timestamps_monotonic = self._filter_recent_request_timestamps(
                request_timestamps_monotonic=endpoint_state.request_timestamps_monotonic,
                now_monotonic=now_monotonic,
            )
            endpoint_state.request_timestamps_monotonic.append(now_monotonic)

    def register_rpc_failure_backoff(self, rpc_url: str, failure_reason: SolanaRpcFailureReason) -> None:
        if failure_reason != SolanaRpcFailureReason.RATE_LIMITED:
            return

        with self._lock:
            endpoint_state = self._resolve_endpoint_state(rpc_url)
            previous_cooldown_until = endpoint_state.cooldown_until_monotonic
            now_monotonic = time.monotonic()
            if now_monotonic >= previous_cooldown_until:
                next_backoff_seconds = settings.SOLANA_RPC_RATE_LIMIT_INITIAL_BACKOFF_SECONDS
            else:
                elapsed_backoff = previous_cooldown_until - now_monotonic
                next_backoff_seconds = min(
                    elapsed_backoff * 2.0,
                    settings.SOLANA_RPC_RATE_LIMIT_MAX_BACKOFF_SECONDS,
                )
            jitter_seconds = random.uniform(0.0, settings.SOLANA_RPC_RATE_LIMIT_JITTER_SECONDS)
            endpoint_state.cooldown_until_monotonic = now_monotonic + next_backoff_seconds + jitter_seconds

    def _resolve_endpoint_state(self, rpc_url: str) -> SolanaRpcEndpointRateLimitState:
        for endpoint_state in self._endpoint_states:
            if endpoint_state.rpc_url == rpc_url:
                return endpoint_state
        endpoint_state = SolanaRpcEndpointRateLimitState(rpc_url=rpc_url)
        self._endpoint_states.append(endpoint_state)
        return endpoint_state

    @staticmethod
    def _filter_recent_request_timestamps(
            request_timestamps_monotonic: list[float],
            now_monotonic: float,
    ) -> list[float]:
        return [
            timestamp_value
            for timestamp_value in request_timestamps_monotonic
            if now_monotonic - timestamp_value < 1.0
        ]

    @staticmethod
    def _resolve_pre_request_sleep_seconds(
            endpoint_state: SolanaRpcEndpointRateLimitState,
            now_monotonic: float,
            minimum_spacing_seconds: float,
    ) -> float:
        cooldown_until = endpoint_state.cooldown_until_monotonic
        if cooldown_until > 0.0 and now_monotonic < cooldown_until:
            return cooldown_until - now_monotonic

        recent_timestamps = SolanaRpcRateLimitStateStore._filter_recent_request_timestamps(
            request_timestamps_monotonic=endpoint_state.request_timestamps_monotonic,
            now_monotonic=now_monotonic,
        )
        endpoint_state.request_timestamps_monotonic = recent_timestamps

        if not recent_timestamps:
            return 0.0

        earliest_timestamp = recent_timestamps[0]
        elapsed_since_earliest = now_monotonic - earliest_timestamp
        if elapsed_since_earliest >= minimum_spacing_seconds:
            return 0.0
        return minimum_spacing_seconds - elapsed_since_earliest


_rate_limit_state_store = SolanaRpcRateLimitStateStore()


def wait_before_rpc_request(rpc_url: str) -> None:
    _rate_limit_state_store.wait_before_rpc_request(rpc_url)


def register_rpc_failure_backoff(rpc_url: str, failure_reason: SolanaRpcFailureReason) -> None:
    _rate_limit_state_store.register_rpc_failure_backoff(rpc_url, failure_reason)


def reset_endpoint_rate_limit_state() -> None:
    _rate_limit_state_store.clear()
