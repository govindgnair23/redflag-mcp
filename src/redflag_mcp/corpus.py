from __future__ import annotations

from pathlib import Path

from redflag_mcp.corpus_install import (
    CorpusActivation,
    CorpusInstallConfig,
    CorpusInstaller,
)


def activate_corpus(
    *,
    cache_dir: Path,
    corpus_package_path: Path | None = None,
    corpus_version: str | None = None,
    release_index_path: Path | None = None,
    auto_update: bool = True,
) -> CorpusActivation:
    return CorpusInstaller(
        CorpusInstallConfig(
            cache_dir=cache_dir,
            corpus_package_path=corpus_package_path,
            corpus_version=corpus_version,
            release_index_path=release_index_path,
            auto_update=auto_update,
        )
    ).activate()
