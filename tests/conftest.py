import pytest


@pytest.fixture
def tmp_vectors_dir(tmp_path):
    """Provide a temporary directory for LanceDB test isolation."""
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    return vectors_dir
