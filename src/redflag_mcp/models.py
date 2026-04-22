from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from redflag_mcp.config import EMBEDDING_DIM, RISK_LEVELS, SIMULATION_TYPES


def _list_or_empty(value: list[str] | None) -> list[str]:
    return list(value or [])


class RedFlagSource(BaseModel):
    """Input model parsed from YAML source files. Used by the ingestion CLI."""

    id: str
    description: str
    product_types: list[str] | None = None
    industry_types: list[str] | None = None
    customer_profiles: list[str] | None = None
    geographic_footprints: list[str] | None = None
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


class RedFlagResult(BaseModel):
    """Response model returned by MCP tools. Omits the embedding vector."""

    id: str
    description: str
    product_types: list[str] = Field(default_factory=list)
    industry_types: list[str] = Field(default_factory=list)
    customer_profiles: list[str] = Field(default_factory=list)
    geographic_footprints: list[str] = Field(default_factory=list)
    regulatory_source: str | None = None
    risk_level: str | None = None
    category: str | None = None
    simulation_type: str | None = None
    source_url: str | None = None
    score: float | None = None


class RedFlagRecord(BaseModel):
    """Storage model written to LanceDB."""

    id: str
    description: str
    product_types: list[str] = Field(default_factory=list)
    industry_types: list[str] = Field(default_factory=list)
    customer_profiles: list[str] = Field(default_factory=list)
    geographic_footprints: list[str] = Field(default_factory=list)
    regulatory_source: str | None = None
    risk_level: str | None = None
    category: str | None = None
    simulation_type: str | None = None
    source_url: str | None = None
    vector: list[float] = Field(default_factory=list)

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

    @field_validator("vector")
    @classmethod
    def validate_vector(cls, v: list[float]) -> list[float]:
        if v and len(v) != EMBEDDING_DIM:
            raise ValueError(f"vector must contain {EMBEDDING_DIM} values, got {len(v)}")
        return v

    @classmethod
    def from_source(cls, source: RedFlagSource, vector: list[float]) -> RedFlagRecord:
        return cls(
            id=source.id,
            description=source.description,
            product_types=_list_or_empty(source.product_types),
            industry_types=_list_or_empty(source.industry_types),
            customer_profiles=_list_or_empty(source.customer_profiles),
            geographic_footprints=_list_or_empty(source.geographic_footprints),
            regulatory_source=source.regulatory_source,
            risk_level=source.risk_level,
            category=source.category,
            simulation_type=source.simulation_type,
            source_url=source.source_url,
            vector=vector,
        )

    def to_result(self, score: float | None = None) -> RedFlagResult:
        return RedFlagResult(
            id=self.id,
            description=self.description,
            product_types=self.product_types,
            industry_types=self.industry_types,
            customer_profiles=self.customer_profiles,
            geographic_footprints=self.geographic_footprints,
            regulatory_source=self.regulatory_source,
            risk_level=self.risk_level,
            category=self.category,
            simulation_type=self.simulation_type,
            source_url=self.source_url,
            score=score,
        )
