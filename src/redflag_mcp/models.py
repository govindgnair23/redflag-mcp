from __future__ import annotations

from pydantic import BaseModel, field_validator

from redflag_mcp.config import RISK_LEVELS, SIMULATION_TYPES


class RedFlagSource(BaseModel):
    """Input model parsed from YAML source files. Used by the ingestion CLI."""

    id: str
    description: str
    product_types: list[str] | None = None
    regulatory_source: str | None = None
    risk_level: str | None = None
    category: str | None = None
    simulation_type: str | None = None
    source_url: str | None = None

    @field_validator("risk_level")
    @classmethod
    def validate_risk_level(cls, v: str | None) -> str | None:
        if v is not None and v not in RISK_LEVELS:
            raise ValueError(f"risk_level must be one of {RISK_LEVELS}, got '{v}'")
        return v

    @field_validator("simulation_type")
    @classmethod
    def validate_simulation_type(cls, v: str | None) -> str | None:
        if v is not None and v not in SIMULATION_TYPES:
            raise ValueError(
                f"simulation_type must be one of {sorted(SIMULATION_TYPES)}, got '{v}'"
            )
        return v
