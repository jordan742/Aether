"""Equity Bot — quantitative execution engine with Stark Circuit Breaker."""
from .bot import EquityBot
from .circuit_breaker import StarkCircuitBreaker
from .signal_watcher import SignalWatcher

__all__ = ["EquityBot", "StarkCircuitBreaker", "SignalWatcher"]
