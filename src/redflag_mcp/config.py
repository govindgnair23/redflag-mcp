from pathlib import Path

# Project root: two levels up from this file (src/redflag_mcp/config.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DATA_DIR = PROJECT_ROOT / "data"
SOURCE_DIR = DATA_DIR / "source"
VECTORS_DIR = DATA_DIR / "vectors"

# Embedding dimension for nomic-embed-text-v1.5
EMBEDDING_DIM = 768

# Valid risk levels
RISK_LEVELS = {"high", "medium", "low"}

# Suggested consultation metadata values. These guide extraction and tagging but
# are intentionally not strict validators; the taxonomy can grow with the corpus.
INDUSTRY_TYPES = {
    "adult_entertainment",
    "art_antiquities",            # NEW — AMLA 2020, FATF DNFBP
    "casinos",                    # was "gaming" — BSA/FFIEC standard term
    "charity_or_nonprofit",       # was "charity_nonprofit" — naming consistency
    "construction",
    "crypto",
    "food_service",
    "government_benefits",
    "import_export",
    "legal_accounting",           # NEW — FATF DNFBP, corruption advisories
    "logistics",
    "luxury_goods",               # NEW — autos, yachts, watches; cash-structuring vector
    "money_services_business",    # was "money_services" — naming consistency
    "oil_and_gas",                # "energy" dropped — oil_and_gas is the AML-relevant subset
    "precious_metals_jewelry",    # NEW — DPMS, FinCEN-defined category
    "professional_services",
    "real_estate",
    "retail",
    "transportation",
}

CUSTOMER_PROFILES = {
    "cash_intensive_business",
    "charity_or_nonprofit",
    "cross_border_business",
    "foreign_financial_institution",
    "foreign_individual",          # NEW — non-resident individuals in cross-border red flags
    "government_benefit_program_sponsor",
    "individual_consumer",
    "money_services_business",
    "newly_established_business",
    "politically_exposed_person",  # NEW — PEPs/SFPFs; corruption and FATF guidance
    "shell_or_front_company",
    "small_business",
    "third_party_payment_processor",
    # "high_risk_business" dropped — circular; risk_level captures this
}

GEOGRAPHIC_FOOTPRINTS = {
    "canada",
    "caribbean",
    "domestic_us",
    "latin_america",
    "mexico",
    "middle_east",
    "southwest_border",
    "uk_eu",
    "china",
    "south_asia",
    "south_east_asia"
}

TYPOLOGY_FAMILIES = {
    "corruption_and_bribery",
    "crypto_asset_money_laundering",
    "fraud_proceeds",
    "human_trafficking_proceeds",
    "narcotics_proceeds",
    "proliferation_financing",
    "real_estate_money_laundering",
    "sanctions_evasion",
    "tax_evasion",
    "terrorist_financing",
    "trade_based_money_laundering",
}

TRANSACTION_PATTERNS = {
    "cash_intensive_behavior",
    "cryptocurrency_mixing",
    "informal_value_transfer",
    "loan_back_scheme",
    "rapid_fund_movement",
    "real_estate_transactions",
    "round_tripping",
    "shell_company_usage",
    "structuring",
    "third_party_payments",
    "trade_document_manipulation",
    "wire_transfer_chains",
}

REGULATORS = {
    # US AML/banking regulators
    "FinCEN", "OFAC", "FFIEC", "OCC", "FRB", "FDIC", "NCUA",
    # US securities / commodities
    "SEC", "CFTC",
    # US law enforcement
    "DOJ", "FBI", "IRS", "DHS",
    # International
    "FATF", "AUSTRAC", "FCA", "EBA", "FINTRAC",
}

# Valid simulation types from docs/Red_flag_types.md
SIMULATION_TYPES = {
    "1A", "1B", "1C", "1D",
    "2A", "2B", "2C",
    "3A", "3B", "3C",
    "4A", "4B",
    "5A", "5B",
    "6",
    "7",
    "8",
}
