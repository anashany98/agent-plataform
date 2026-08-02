"""Canonical catalogue-origin policy shared by imports and deterministic tools."""

from __future__ import annotations

import re
import unicodedata

DEMO_SOURCE_SQL_ALIASES = frozenset(
    {
        "demo",
        "demo data",
        "demo-data",
        "demo_data",
        "example",
        "fixture",
        "mock",
        "sample",
        "seed",
        "synthetic",
        "test",
    }
)
TRUSTED_PRODUCTION_CATALOG_SOURCES = frozenset({"import", "local", "prestashop"})


def normalize_product_source(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "import")).strip().casefold()
    alias_key = re.sub(r"[\s_-]+", "-", normalized)
    demo_alias_keys = {re.sub(r"[\s_-]+", "-", alias) for alias in DEMO_SOURCE_SQL_ALIASES}
    return "demo" if alias_key in demo_alias_keys else normalized


def is_demo_source(value: object) -> bool:
    return normalize_product_source(value) == "demo"


def is_trusted_product_source(value: object) -> bool:
    return normalize_product_source(value) in TRUSTED_PRODUCTION_CATALOG_SOURCES
