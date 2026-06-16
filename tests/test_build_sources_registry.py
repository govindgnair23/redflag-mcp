"""Tests for scripts/build_sources_registry.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import build_sources_registry


def test_pdflinks_path_uses_source_file_catalogue():
    assert build_sources_registry.PDFLINKS_PATH.name == "pdflinks.txt"
    assert "source_file_catalogue" in str(build_sources_registry.PDFLINKS_PATH)
    assert build_sources_registry.SOURCES_REGISTRY_PATH.name == "sources.yaml"
    assert "source_file_catalogue" not in str(build_sources_registry.SOURCES_REGISTRY_PATH)
