from pathlib import Path
from urllib.parse import urlparse

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
PRODUCT_TYPES = {
    "ach",
    "check_cashing",
    "correspondent_banking",
    "credit_card",
    "crypto",
    "currency_exchange",
    "depository",
    "insurance",
    "money_transmitter",
    "prepaid",
    "private_banking",
    "remittance",
    "securities",
    "trade_finance",
    "wire_transfer",
}

CATEGORIES = {
    "corruption",
    "cyber_enabled",
    "fraud_nexus",
    "human_smuggling",
    "human_trafficking",
    "layering",
    "narcotics_trafficking",
    "proliferation_financing",
    "ransomware",
    "sanctions_evasion",
    "shell_company",
    "structuring",
    "tax_evasion",
    "terrorist_financing",
    "trade_based_money_laundering",
    "virtual_currency",
}

INDUSTRY_TYPES = {
    "adult_entertainment",
    "art_antiquities",            # NEW — AMLA 2020, FATF DNFBP
    "arms_dual_use_goods",
    "auto_sales",
    "casinos",                    # was "gaming" — BSA/FFIEC standard term
    "charity_or_nonprofit",       # was "charity_nonprofit" — naming consistency
    "construction",
    "crypto",
    "food_service",
    "government_benefits",
    "healthcare",
    "import_export",
    "legal_accounting",           # NEW — FATF DNFBP, corruption advisories
    "logistics",
    "luxury_goods",               # NEW — autos, yachts, watches; cash-structuring vector
    "maritime_shipping",
    "money_services_business",    # was "money_services" — naming consistency
    "oil_and_gas",                # "energy" dropped — oil_and_gas is the AML-relevant subset
    "online_marketplace",
    "payroll",
    "precious_metals_jewelry",    # NEW — DPMS, FinCEN-defined category
    "professional_services",
    "real_estate",
    "retail",
    "travel_hospitality",
    "transportation",
}

CUSTOMER_PROFILES = {
    "beneficial_owner_obscured",
    "cash_intensive_business",
    "charity_or_nonprofit",
    "cross_border_business",
    "elderly_or_vulnerable_person",
    "foreign_financial_institution",
    "foreign_individual",          # NEW — non-resident individuals in cross-border red flags
    "government_official",
    "government_benefit_program_sponsor",
    "high_net_worth_individual",
    "individual_consumer",
    "migrant_worker",
    "money_services_business",
    "newly_established_business",
    "non_resident_alien",
    "politically_exposed_person",  # NEW — PEPs/SFPFs; corruption and FATF guidance
    "shell_or_front_company",
    "small_business",
    "student",
    "third_party_payment_processor",
    # "high_risk_business" dropped — circular; risk_level captures this
}

GEOGRAPHIC_FOOTPRINTS = {
    "canada",
    "caribbean",
    "central_america",
    "china",
    "domestic_us",
    "eastern_europe",
    "high_risk_jurisdiction",
    "iran",
    "latin_america",
    "mexico",
    "middle_east",
    "north_korea",
    "ofac_sanctioned_country",
    "russia",
    "sanctioned_jurisdiction",
    "south_asia",
    "south_east_asia",
    "southwest_border",
    "uk_eu",
    "venezuela",
    "west_africa",
}

TYPOLOGY_FAMILIES = {
    "corruption_and_bribery",
    "crypto_asset_money_laundering",
    "cybercrime_proceeds",
    "elder_financial_exploitation",
    "environmental_crime_proceeds",
    "fraud_proceeds",
    "human_smuggling_proceeds",
    "human_trafficking_proceeds",
    "narcotics_proceeds",
    "organized_crime_proceeds",
    "proliferation_financing",
    "real_estate_money_laundering",
    "sanctions_evasion",
    "scam_proceeds",
    "tax_evasion",
    "terrorist_financing",
    "trade_based_money_laundering",
}

TRANSACTION_PATTERNS = {
    "account_takeover",
    "cash_deposits_below_threshold",
    "cash_intensive_behavior",
    "cryptocurrency_mixing",
    "funnel_account_activity",
    "identity_misrepresentation",
    "informal_value_transfer",
    "invoice_mismatch",
    "loan_back_scheme",
    "monetary_instrument_purchases",
    "money_mule_activity",
    "nested_account_activity",
    "pass_through_account_activity",
    "rapid_fund_movement",
    "real_estate_transactions",
    "round_tripping",
    "shell_company_usage",
    "structuring",
    "third_party_payments",
    "trade_document_manipulation",
    "unusual_international_wires",
    "wire_transfer_chains",
}

REGULATORS = {
    # US AML/banking regulators
    "FinCEN", "FinCEN-BIS", "FinCEN-IRS-CI", "OFAC", "FFIEC", "OCC", "FRB", "FDIC", "NCUA",
    # US securities / commodities
    "SEC", "CFTC", "FINRA",
    # US law enforcement
    "DOJ", "FBI", "IRS", "DHS",
    # Europe / UK
    "AMLA", "EBA", "ECB", "ESMA", "Europol", "FCA", "FIU-NL", "BaFin", "AMF-France", "ACPR",
    "NCA", "OFSI", "CSSF", "AFM",
    # Asia-Pacific
    "MAS", "HKMA", "SFC-HK", "JFSA", "JFIU", "AUSTRAC", "ASIC", "APRA", "NPA",
    # Middle East / South Asia
    "CBUAE", "SAMA", "RBI",
    # Canada / international bodies
    "FINTRAC", "FATF", "INTERPOL", "UN", "UNODC", "WorldBank", "IMF",
}

REGULATOR_JURISDICTIONS = {
    # US AML/banking regulators
    "FinCEN": "US",
    "FinCEN-BIS": "US",
    "FinCEN-IRS-CI": "US",
    "OFAC": "US",
    "FFIEC": "US",
    "OCC": "US",
    "FRB": "US",
    "FDIC": "US",
    "NCUA": "US",
    "SEC": "US",
    "CFTC": "US",
    "DOJ": "US",
    "FBI": "US",
    "IRS": "US",
    "DHS": "US",
    # Europe / UK
    "AMF-France": "FR",
    "ACPR": "FR",
    "FCA": "GB",
    "AMLA": "EU",
    "EBA": "EU",
    "ESMA": "EU",
    "ECB": "EU",
    "Europol": "EU",
    "FIU-NL": "NL",
    "BaFin": "DE",
    "NCA": "GB",
    "OFSI": "GB",
    "CSSF": "LU",
    "AFM": "NL",
    # Asia-Pacific
    "MAS": "SG",
    "HKMA": "HK",
    "SFC-HK": "HK",
    "JFSA": "JP",
    "JFIU": "JP",
    "NPA": "JP",
    "AUSTRAC": "AU",
    "ASIC": "AU",
    "APRA": "AU",
    # Middle East / South Asia
    "CBUAE": "AE",
    "SAMA": "SA",
    "RBI": "IN",
    "FINRA": "US",
    # Canada / international bodies
    "FINTRAC": "CA",
    "FATF": "FATF",
    "INTERPOL": "INTERPOL",
    "UN": "UN",
    "UNODC": "UN",
    "WorldBank": "WB",
    "IMF": "IMF",
}


def jurisdiction_for_regulator(regulator: str | None) -> str | None:
    """Return the canonical jurisdiction code for a known regulator."""
    if not regulator:
        return None
    return REGULATOR_JURISDICTIONS.get(regulator)


URL_DOMAIN_TO_REGULATOR: dict[str, str] = {
    "ofac.treasury.gov": "OFAC",
    "home.treasury.gov": "OFAC",
    "www.fincen.gov": "FinCEN",
    "bsaaml.ffiec.gov": "FFIEC",
    "www.ic3.gov": "FBI",
    "www.irs.gov": "IRS",
    "www.finra.org": "FINRA",
    "fintrac-canafe.canada.ca": "FINTRAC",
    "www.handbook.fca.org.uk": "FCA",
    "www.nationalcrimeagency.gov.uk": "NCA",
    "assets.publishing.service.gov.uk": "OFSI",
    "www.gov.uk": "OFSI",
    "www.eba.europa.eu": "EBA",
    "www.europol.europa.eu": "Europol",
    "www.afm.nl": "AFM",
    "www.mas.gov.sg": "MAS",
    "www.hkma.gov.hk": "HKMA",
    "www.sfc.hk": "SFC-HK",
    "www.jfiu.gov.hk": "JFIU",
    "www.npa.go.jp": "NPA",
    "www.austrac.gov.au": "AUSTRAC",
    "www.fatf-gafi.org": "FATF",
    "www.centralbank.ae": "CBUAE",
    "rulebook.centralbank.ae": "CBUAE",
    "www.sama.gov.sa": "SAMA",
    "www.rbi.org.in": "RBI",
    "fiuindia.gov.in": "RBI",
    "fiaumalta.org": "FATF",
    "www.cssf.lu": "CSSF",
    "www.coe.int": "FATF",
    "www.ppatk.go.id": "FATF",
    "www.amlo.go.th": "FATF",
    "www.amlc.gov.ph": "FATF",
    "www.mjib.gov.tw": "FATF",
    "www.kofiu.go.kr": "FATF",
    "www.drs.customs.gov.hk": "HKMA",
    "abs.org.sg": "MAS",
    "assets.adgm.com": "CBUAE",
}


def regulator_from_url(url: str | None) -> str | None:
    """Infer the regulator from a source URL's domain.

    Returns the regulator string if the domain is recognised, or None otherwise.
    """
    if not url:
        return None
    try:
        domain = urlparse(url).netloc
    except Exception:
        return None
    return URL_DOMAIN_TO_REGULATOR.get(domain)


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
