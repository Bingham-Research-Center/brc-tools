"""Explicit observation unit conversions; no magnitude-based guesses."""

from __future__ import annotations

import math


def convert(value, unit):
    if value is None or not math.isfinite(value):
        return None, None, "missing"
    key = str(unit).strip().lower().replace("°", "").replace(" ", "")
    table = {
        "celsius": (1, 0, "degC"),
        "degc": (1, 0, "degC"),
        "c": (1, 0, "degC"),
        "kelvin": (1, -273.15, "degC"),
        "k": (1, -273.15, "degC"),
        "fahrenheit": (5 / 9, -32 * 5 / 9, "degC"),
        "degf": (5 / 9, -32 * 5 / 9, "degC"),
        "pa": (1, 0, "Pa"),
        "pascals": (1, 0, "Pa"),
        "hpa": (100, 0, "Pa"),
        "mb": (100, 0, "Pa"),
        "inhg": (3386.389, 0, "Pa"),
        "m/s": (1, 0, "m/s"),
        "meters/second": (1, 0, "m/s"),
        "knots": (0.5144444444444445, 0, "m/s"),
        "kts": (0.5144444444444445, 0, "m/s"),
        "mph": (0.44704, 0, "m/s"),
        "km/h": (1 / 3.6, 0, "m/s"),
        "millimeters": (0.001, 0, "m"),
        "mm": (0.001, 0, "m"),
        "cm": (0.01, 0, "m"),
        "centimeters": (0.01, 0, "m"),
        "meters": (1, 0, "m"),
        "m": (1, 0, "m"),
        "inches": (0.0254, 0, "m"),
        "in": (0.0254, 0, "m"),
        "feet": (0.3048, 0, "m"),
        "ft": (0.3048, 0, "m"),
        "%": (1, 0, "%"),
        "percent": (1, 0, "%"),
        "degrees": (1, 0, "degree"),
        "degree": (1, 0, "degree"),
        "w/m**2": (1, 0, "W/m2"),
        "w/m2": (1, 0, "W/m2"),
        "w/m^2": (1, 0, "W/m2"),
        "m3/m3": (1, 0, "m3/m3"),
        "m**3/m**3": (1, 0, "m3/m3"),
    }
    if key not in table:
        return None, None, "unknown_unit"
    scale, offset, target = table[key]
    return value * scale + offset, target, "converted"
