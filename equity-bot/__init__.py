"""Equity Bot — quantitative execution engine with Stark Circuit Breaker."""
from .bot import EquityBot
from .circuit_breaker import StarkCircuitBreaker

__all__ = ["EquityBot", "StarkCircuitBreaker"]
