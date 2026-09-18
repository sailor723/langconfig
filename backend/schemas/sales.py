"""
Canonical schemas for sales data.

Single source of truth for the cleaned sales data shape.
Both `market_wizard` (data prep) and `finance_pro` (analysis) reference this.

WHY: Avoids schema drift between wizard output and analysis input.
FUTURE: Replace with dbt models when we move to production-grade data pipeline.
"""
from pydantic import BaseModel, Field
from typing import Literal


# ── Canonical schema (post-cleaning) ─────────────────────────────────

Region = Literal["US", "EMEA", "APAC", "LATAM"]
ProductCategory = Literal["Software", "Hardware", "Services"]


class CleanedSalesRow(BaseModel):
    """One row of cleaned sales data.

    This is the OUTPUT of market_wizard and INPUT to finance_pro.
    Field changes here affect BOTH skills — that's intentional.
    """
    transaction_id: str = Field(..., description="Unique transaction identifier")
    region: Region = Field(..., description="Sales region — drives tax rate")
    product_category: ProductCategory = Field(..., description="Product type")
    quantity: int = Field(..., ge=0, description="Units sold (NOT revenue)")
    unit_price: float = Field(..., gt=0, description="Price per unit, before discount")
    discount: float = Field(default=0.0, ge=0, description="Absolute discount in USD")


# ── Schema registry (for wizard to reference by name) ────────────────

SCHEMAS: dict[str, type[BaseModel]] = {
    "CleanedSalesRow": CleanedSalesRow,
}


def get_schema(name: str) -> type[BaseModel]:
    """Look up a schema by name."""
    if name not in SCHEMAS:
        raise KeyError(f"Unknown schema: {name}. Available: {list(SCHEMAS)}")
    return SCHEMAS[name]