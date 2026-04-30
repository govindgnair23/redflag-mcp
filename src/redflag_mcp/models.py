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
    regulator: str | None = None
    issued_date: str | None = None
    risk_level: str | None = None
    category: str | None = None
    simulation_type: str | None = None
    source_url: str | None = None
    typology_family: list[str] | None = None
    transaction_patterns: list[str] | None = None
    key_terms: list[str] | None = None

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
    regulator: str | None = None
    issued_date: str | None = None
    risk_level: str | None = None
    category: str | None = None
    simulation_type: str | None = None
    source_url: str | None = None
    typology_family: list[str] = Field(default_factory=list)
    transaction_patterns: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
    score: float | None = None
    fit_explanation: str | None = None
    fit_signals: list[str] = Field(default_factory=list)


class SourceRedFlagSnippet(BaseModel):
    """Bounded red flag context returned with source detail responses."""

    id: str
    description_snippet: str
    category: str | None = None
    risk_level: str | None = None


class RedFlagSourceSummary(BaseModel):
    """Source-level coverage summary derived from ingested red flag records."""

    source_id: str
    regulatory_source: str | None = None
    source_url: str | None = None
    red_flag_count: int
    categories: list[str] = Field(default_factory=list)
    risk_levels: list[str] = Field(default_factory=list)
    product_types: list[str] = Field(default_factory=list)
    red_flag_ids: list[str] = Field(default_factory=list)


class RedFlagSourceDetail(RedFlagSourceSummary):
    """Bounded source detail for source browsing tools and resources."""

    industry_types: list[str] = Field(default_factory=list)
    customer_profiles: list[str] = Field(default_factory=list)
    geographic_footprints: list[str] = Field(default_factory=list)
    red_flags: list[SourceRedFlagSnippet] = Field(default_factory=list)


class RedFlagRecord(BaseModel):
    """Storage model written to LanceDB."""

    id: str
    description: str
    product_types: list[str] = Field(default_factory=list)
    industry_types: list[str] = Field(default_factory=list)
    customer_profiles: list[str] = Field(default_factory=list)
    geographic_footprints: list[str] = Field(default_factory=list)
    regulatory_source: str | None = None
    regulator: str | None = None
    issued_date: str | None = None
    risk_level: str | None = None
    category: str | None = None
    simulation_type: str | None = None
    source_url: str | None = None
    typology_family: list[str] = Field(default_factory=list)
    transaction_patterns: list[str] = Field(default_factory=list)
    key_terms: list[str] = Field(default_factory=list)
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
            regulator=source.regulator,
            issued_date=source.issued_date,
            risk_level=source.risk_level,
            category=source.category,
            simulation_type=source.simulation_type,
            source_url=source.source_url,
            typology_family=_list_or_empty(source.typology_family),
            transaction_patterns=_list_or_empty(source.transaction_patterns),
            key_terms=_list_or_empty(source.key_terms),
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
            regulator=self.regulator,
            issued_date=self.issued_date,
            risk_level=self.risk_level,
            category=self.category,
            simulation_type=self.simulation_type,
            source_url=self.source_url,
            typology_family=self.typology_family,
            transaction_patterns=self.transaction_patterns,
            key_terms=self.key_terms,
            score=score,
        )
