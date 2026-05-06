from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from redflag_mcp.config import EMBEDDING_DIM, RISK_LEVELS, SIMULATION_TYPES


def _list_or_empty(value: list[str] | None) -> list[str]:
    return list(value or [])


class RedFlagSource(BaseModel):
    """Input model parsed from YAML source files. Used by the ingestion CLI."""

    model_config = ConfigDict(extra="allow")

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
    fit_explanation: str | None = None
    fit_signals: list[str] = Field(default_factory=list)


class CorpusMetadata(BaseModel):
    """Version and integrity metadata for a packaged local corpus."""

    version: str
    schema_version: int = Field(gt=0)
    build_timestamp: str
    package_id: str
    file_hashes: dict[str, str]
    integrity_status: Literal["unverified", "verified", "failed"]
    record_count: int = Field(ge=0)
    source_count: int = Field(ge=0)

    @field_validator("file_hashes")
    @classmethod
    def validate_file_hashes(cls, v: dict[str, str]) -> dict[str, str]:
        for file_name, digest in v.items():
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError(
                    f"file hash for {file_name} must be a lowercase SHA-256 digest"
                )
        return v


class SourceReleaseMetadata(BaseModel):
    """Reviewed source-level metadata layered over the generated URL registry."""

    title: str | None = None
    authority: str | None = None
    jurisdiction: str | None = None
    publication_date: str | None = None
    redistribution_status: Literal[
        "url_only", "bundled_allowed", "restricted"
    ] = "url_only"
    source_document_sha256: str | None = None

    @field_validator("source_document_sha256")
    @classmethod
    def validate_source_document_sha256(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError("source_document_sha256 must be a lowercase SHA-256 digest")
        return v


class SourceManifestEntry(SourceReleaseMetadata):
    """Source metadata after merging reviewed metadata with the source URL registry."""

    source_key: str
    source_url: str | None = None
    bundle_source_asset: bool = False

    @model_validator(mode="after")
    def set_bundle_policy(self) -> SourceManifestEntry:
        self.bundle_source_asset = self.redistribution_status == "bundled_allowed"
        return self


def build_source_manifest(
    source_metadata: dict[str, SourceReleaseMetadata],
    source_registry: dict[str, dict[str, str | None]],
) -> dict[str, SourceManifestEntry]:
    """Merge reviewed source metadata with generated source URLs."""

    unknown_keys = sorted(set(source_metadata) - set(source_registry))
    if unknown_keys:
        raise ValueError(f"source metadata references unknown source keys: {unknown_keys}")

    manifest: dict[str, SourceManifestEntry] = {}
    for source_key in sorted(source_registry):
        metadata = source_metadata.get(source_key) or SourceReleaseMetadata()
        manifest[source_key] = SourceManifestEntry(
            **metadata.model_dump(),
            source_key=source_key,
            source_url=source_registry[source_key].get("url"),
        )
    return manifest


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
