"""Una sola instancia de `nublock run` por base de datos (dos trackers duplicarían el tiempo)."""

import fcntl
import os
from pathlib import Path
from typing import IO

ALREADY_RUNNING_EXIT_CODE = 3  # Nublock.app lo usa para abrir el dashboard en vez de otra copia


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: IO[str] | None = None

    def acquire(self) -> bool:
        """True si somos la única instancia. El lock dura mientras el proceso viva."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+", encoding="utf-8")
        try:
            # flock: lock del OS sobre el archivo. LOCK_NB = no esperar si otro lo tiene.
            # Si el proceso muere (incluso por un crash), el OS lo libera solo.
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            file.close()
            return False
        file.seek(0)
        file.truncate()
        file.write(f"{os.getpid()}\n")
        file.flush()
        self._file = file
        return True

    def release(self) -> None:
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
            self._file = None

    def held_by_other(self) -> bool:
        """¿Hay otra instancia corriendo? (sin quedarse con el lock)."""
        if self.acquire():
            self.release()
            return False
        return True
