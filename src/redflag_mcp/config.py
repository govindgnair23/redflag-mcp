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
    "charity_nonprofit",
    "construction",
    "energy",
    "food_service",
    "gaming",
    "government_benefits",
    "import_export",
    "logistics",
    "money_services",
    "oil_and_gas",
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
    "government_benefit_program_sponsor",
    "high_risk_business",
    "individual_consumer",
    "money_services_business",
    "newly_established_business",
    "shell_or_front_company",
    "small_business",
    "third_party_payment_processor",
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
