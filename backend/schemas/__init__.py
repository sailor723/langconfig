"""Canonical schemas — single source of truth for data shape."""
from .sales import CleanedSalesRow, SCHEMAS, get_schema

__all__ = ["CleanedSalesRow", "SCHEMAS", "get_schema"]