from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from redflag_mcp.lexicalstore import LEXICAL_SCHEMA_VERSION, LexicalStore


class CorpusInstallError(RuntimeError):
    """Raised when no verified corpus can be activated."""


@dataclass(frozen=True)
class CorpusInstallConfig:
    cache_dir: Path
    corpus_package_path: Path | None = None
    corpus_version: str | None = None
    release_index_path: Path | None = None
    auto_update: bool = True


@dataclass(frozen=True)
class CorpusActivation:
    version: str
    sqlite_path: Path
    manifest_path: Path


class CorpusInstaller:
    def __init__(self, config: CorpusInstallConfig) -> None:
        self.config = config

    def activate(self) -> CorpusActivation:
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        if not self.config.auto_update:
            active = self._read_active()
            if active is not None:
                return active

        if self.config.corpus_package_path is not None:
            return self._install_package(self.config.corpus_package_path)

        release = self._select_release()
        if release is not None:
            artifact = Path(release["artifact"])
            activation = self._install_package(artifact, expected_sha256=release.get("sha256"))
            if self.config.corpus_version and activation.version != self.config.corpus_version:
                raise CorpusInstallError(
                    f"Activated corpus {activation.version}, expected {self.config.corpus_version}"
                )
            return activation

        active = self._read_active()
        if active is not None:
            return active
        raise CorpusInstallError("No verified corpus is installed and no release index is configured")

    def _select_release(self) -> dict[str, Any] | None:
        if self.config.release_index_path is None:
            return None
        index = json.loads(self.config.release_index_path.read_text())
        releases = index.get("releases") or []
        if self.config.corpus_version:
            for release in releases:
                if release.get("version") == self.config.corpus_version:
                    return release
            raise CorpusInstallError(
                f"Corpus version {self.config.corpus_version} not found in release index"
            )
        latest = index.get("latest_compatible_version")
        for release in releases:
            if release.get("version") == latest:
                return release
        return releases[0] if releases else None

    def _install_package(
        self, package_path: Path, expected_sha256: str | None = None
    ) -> CorpusActivation:
        if expected_sha256 and _sha256_file(package_path) != expected_sha256:
            raise CorpusInstallError("Corpus package verification failed: package hash mismatch")
        try:
            with zipfile.ZipFile(package_path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                self._verify_archive_files(archive, manifest)
                version = manifest["version"]
                install_dir = self.config.cache_dir / "corpora" / version
                temp_dir = self.config.cache_dir / "corpora" / f".{version}.tmp"
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                temp_dir.mkdir(parents=True)
                (temp_dir / "manifest.json").write_text(
                    json.dumps(manifest, indent=2, sort_keys=True)
                )
                (temp_dir / "redflags.sqlite").write_bytes(archive.read("redflags.sqlite"))
        except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            raise CorpusInstallError(
                f"Corpus package verification failed: {exc}"
            ) from exc

        if install_dir.exists():
            shutil.rmtree(install_dir)
        temp_dir.rename(install_dir)
        sqlite_path = install_dir / "redflags.sqlite"
        LexicalStore.open(sqlite_path)
        activation = CorpusActivation(
            version=version,
            sqlite_path=sqlite_path,
            manifest_path=install_dir / "manifest.json",
        )
        self._write_active(activation)
        return activation

    def _verify_archive_files(
        self, archive: zipfile.ZipFile, manifest: dict[str, Any]
    ) -> None:
        if manifest.get("schema_version") != LEXICAL_SCHEMA_VERSION:
            raise CorpusInstallError(
                "Corpus package verification failed: unsupported schema version"
            )
        names = set(archive.namelist())
        for file_name, expected_hash in (manifest.get("file_hashes") or {}).items():
            if file_name not in names:
                raise CorpusInstallError(
                    f"Corpus package verification failed: missing {file_name}"
                )
            actual_hash = hashlib.sha256(archive.read(file_name)).hexdigest()
            if actual_hash != expected_hash:
                raise CorpusInstallError(
                    f"Corpus package verification failed: {file_name} hash mismatch"
                )

    def _read_active(self) -> CorpusActivation | None:
        active_path = self.config.cache_dir / "active.json"
        if not active_path.exists():
            return None
        payload = json.loads(active_path.read_text())
        activation = CorpusActivation(
            version=payload["version"],
            sqlite_path=Path(payload["sqlite_path"]),
            manifest_path=Path(payload["manifest_path"]),
        )
        if activation.sqlite_path.exists() and activation.manifest_path.exists():
            LexicalStore.open(activation.sqlite_path)
            return activation
        return None

    def _write_active(self, activation: CorpusActivation) -> None:
        active_path = self.config.cache_dir / "active.json"
        active_path.write_text(
            json.dumps(
                {
                    "version": activation.version,
                    "sqlite_path": str(activation.sqlite_path),
                    "manifest_path": str(activation.manifest_path),
                },
                indent=2,
                sort_keys=True,
            )
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
