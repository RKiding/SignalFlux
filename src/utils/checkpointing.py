import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger


def _atomic_write_text(path: str, content: str, encoding: str = "utf-8") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


def _atomic_write_json(path: str, data: Any) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    _atomic_write_text(path, content)


def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@dataclass
class CheckpointManager:
    base_dir: str
    run_id: str

    @property
    def run_dir(self) -> str:
        return os.path.join(self.base_dir, self.run_id)

    def path(self, name: str) -> str:
        return os.path.join(self.run_dir, name)

    def exists(self, name: str) -> bool:
        return os.path.exists(self.path(name))

    def save_json(self, name: str, data: Any) -> None:
        try:
            _atomic_write_json(self.path(name), data)
        except Exception as e:
            logger.warning(f"Failed to write checkpoint json {name}: {e}")

    def load_json(self, name: str, default: Optional[Any] = None) -> Any:
        try:
            p = self.path(name)
            if not os.path.exists(p):
                return default
            return _read_json(p)
        except Exception as e:
            logger.warning(f"Failed to read checkpoint json {name}: {e}")
            return default

    def save_text(self, name: str, text: str) -> None:
        try:
            _atomic_write_text(self.path(name), text)
        except Exception as e:
            logger.warning(f"Failed to write checkpoint text {name}: {e}")

    def load_text(self, name: str, default: str = "") -> str:
        try:
            p = self.path(name)
            if not os.path.exists(p):
                return default
            return _read_text(p)
        except Exception as e:
            logger.warning(f"Failed to read checkpoint text {name}: {e}")
            return default


def resolve_latest_run_id(checkpoint_base_dir: str) -> Optional[str]:
    try:
        if not os.path.isdir(checkpoint_base_dir):
            return None
        candidates = [d for d in os.listdir(checkpoint_base_dir) if os.path.isdir(os.path.join(checkpoint_base_dir, d))]
        if not candidates:
            return None
        candidates.sort(reverse=True)
        return candidates[0]
    except Exception:
        return None
