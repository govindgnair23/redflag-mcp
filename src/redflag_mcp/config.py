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
