from collections.abc import Iterator

import pytest

from nublock.storage import MEMORY, Repository


@pytest.fixture
def repo() -> Iterator[Repository]:
    """Repository con SQLite en RAM: cada test parte con una DB vacía."""
    repository = Repository(MEMORY)
    yield repository
    repository.close()
