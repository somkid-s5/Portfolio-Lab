"""Input validation and deterministic synthetic quote calculation."""
from __future__ import annotations

import math
from typing import Any


MAX_WEIGHT_KG = 1000.0
MAX_DISTANCE_KM = 5000.0
SERVICE_LEVELS = ("standard", "express")


def _finite_number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} is outside the supported numeric range") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}")
    return number


def validate_quote_request(payload: Any) -> dict[str, float | str]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be a JSON object")
    weight = _finite_number(payload.get("weight_kg"), "weight_kg", 0.1, MAX_WEIGHT_KG)
    distance = _finite_number(payload.get("distance_km"), "distance_km", 1, MAX_DISTANCE_KM)
    level = payload.get("service_level")
    if not isinstance(level, str) or level not in SERVICE_LEVELS:
        raise ValueError("service_level must be standard or express")
    return {"weight_kg": weight, "distance_km": distance, "service_level": level}


def validate_rules(rules: Any) -> dict[str, Any]:
    if not isinstance(rules, dict):
        raise ValueError("pricing rules must be an object")
    version = rules.get("rules_version")
    if not isinstance(version, str) or not version.strip() or len(version) > 32:
        raise ValueError("rules_version must be a non-empty string of at most 32 characters")
    rates = rules.get("rates")
    if not isinstance(rates, dict):
        raise ValueError("rates must be an object")
    base = _finite_number(rates.get("base_thb"), "base_thb", 0, 100000)
    per_kg = _finite_number(rates.get("per_kg_thb"), "per_kg_thb", 0, 10000)
    per_km = _finite_number(rates.get("per_km_thb"), "per_km_thb", 0, 10000)
    multipliers = rules.get("service_multipliers")
    if not isinstance(multipliers, dict):
        raise ValueError("service_multipliers must be an object")
    clean_multipliers = {}
    for level in SERVICE_LEVELS:
        clean_multipliers[level] = _finite_number(
            multipliers.get(level), f"service_multipliers.{level}", 0.1, 10
        )
    eta = rules.get("estimated_days")
    if not isinstance(eta, dict):
        raise ValueError("estimated_days must be an object")
    clean_eta = {}
    for level in SERVICE_LEVELS:
        days = eta.get(level)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
            raise ValueError(f"estimated_days.{level} must be an integer from 1 to 30")
        clean_eta[level] = days
    return {
        "rules_version": version.strip(),
        "rates": {"base_thb": base, "per_kg_thb": per_kg, "per_km_thb": per_km},
        "service_multipliers": clean_multipliers,
        "estimated_days": clean_eta,
    }


def calculate_quote(payload: Any, rules: Any) -> dict[str, Any]:
    request = validate_quote_request(payload)
    pricing = validate_rules(rules)
    rates = pricing["rates"]
    subtotal = (
        rates["base_thb"]
        + request["weight_kg"] * rates["per_kg_thb"]
        + request["distance_km"] * rates["per_km_thb"]
    )
    amount = round(subtotal * pricing["service_multipliers"][request["service_level"]], 2)
    return {
        "amount_thb": amount,
        "currency": "THB",
        "estimated_days": pricing["estimated_days"][request["service_level"]],
        "rules_version": pricing["rules_version"],
    }
