"""Private, atomically persisted settings for Netmon's authenticated web UI.

The file managed here contains values that must never be committed to Git or
returned to the browser:

* a Werkzeug ``scrypt`` password hash (the plaintext password is never stored);
* a random Flask session-signing secret;
* the optional Groq API key;
* the persistent Remote AI on/off state and last connection-test result.

Only the unprivileged ``netmon`` service account and root can read the file. A
small lock file serialises updates, and ``os.replace`` makes each write atomic,
so the collector can safely read settings while the web process changes them.
"""

from __future__ import annotations

import fcntl
import json
import os
import secrets
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from werkzeug.security import check_password_hash, generate_password_hash


DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
MINIMUM_ADMIN_PASSWORD_LENGTH = 12


@dataclass(frozen=True, slots=True)
class SecureSettings:
    """The complete private settings document as an immutable value object."""

    session_secret: str
    admin_password_hash: str = ""
    password_created_at: str = ""
    ai_api_key: str = ""
    ai_enabled: bool = False
    ai_base_url: str = DEFAULT_GROQ_BASE_URL
    ai_model: str = DEFAULT_GROQ_MODEL
    ai_last_test_ok: bool = False
    ai_last_test_at: str = ""
    ai_last_error: str = ""

    @property
    def admin_configured(self) -> bool:
        return bool(self.admin_password_hash)

    @property
    def ai_key_active(self) -> bool:
        return bool(self.ai_api_key and self.ai_last_test_ok)


class SettingsStore:
    """Read and update one mode-0600 private JSON settings file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_name(f".{self.path.name}.lock")

    @contextmanager
    def _lock(self, *, exclusive: bool) -> Iterator[None]:
        """Hold a process-wide advisory lock around a read or write."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.chmod(self.lock_path, 0o600)
            operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(descriptor, operation)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @staticmethod
    def _new_defaults() -> SecureSettings:
        """Create defaults with a high-entropy session-signing secret."""

        return SecureSettings(session_secret=secrets.token_urlsafe(64))

    @staticmethod
    def _normalise(payload: dict[str, object]) -> SecureSettings:
        """Load old/partial documents safely by applying current defaults."""

        defaults = asdict(SettingsStore._new_defaults())
        allowed = set(defaults)
        defaults.update({key: value for key, value in payload.items() if key in allowed})

        # A missing or damaged session secret must never result in a predictable
        # Flask signing key. Replace it with fresh entropy before continuing.
        if not isinstance(defaults["session_secret"], str) or not defaults["session_secret"]:
            defaults["session_secret"] = secrets.token_urlsafe(64)

        return SecureSettings(
            session_secret=str(defaults["session_secret"]),
            admin_password_hash=str(defaults["admin_password_hash"]),
            password_created_at=str(defaults["password_created_at"]),
            ai_api_key=str(defaults["ai_api_key"]),
            ai_enabled=bool(defaults["ai_enabled"]),
            ai_base_url=str(defaults["ai_base_url"] or DEFAULT_GROQ_BASE_URL),
            ai_model=str(defaults["ai_model"] or DEFAULT_GROQ_MODEL),
            ai_last_test_ok=bool(defaults["ai_last_test_ok"]),
            ai_last_test_at=str(defaults["ai_last_test_at"]),
            ai_last_error=str(defaults["ai_last_error"]),
        )

    def _read_unlocked(self) -> SecureSettings:
        if not self.path.exists():
            settings = self._new_defaults()
            self._write_unlocked(settings)
            return settings

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Could not read private settings from {self.path}: {exc}"
            ) from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"Private settings file {self.path} is not a JSON object")

        settings = self._normalise(payload)
        os.chmod(self.path, 0o600)
        return settings

    def _write_unlocked(self, settings: SecureSettings) -> None:
        """Write a complete document beside the target, then atomically replace."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
            text=True,
        )
        temporary = Path(temporary_name)

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(asdict(settings), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary.exists():
                temporary.unlink()

    def load(self) -> SecureSettings:
        """Return current settings, creating a secure default file if absent."""

        # Creation is a write, so the first load needs an exclusive lock. The
        # file is tiny and the lock is held for only a few milliseconds.
        with self._lock(exclusive=True):
            return self._read_unlocked()

    def _save(self, settings: SecureSettings) -> SecureSettings:
        with self._lock(exclusive=True):
            self._write_unlocked(settings)
        return settings

    def set_admin_password(self, password: str) -> SecureSettings:
        """Hash and persist a new administrator password using scrypt."""

        if len(password) < MINIMUM_ADMIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Password must contain at least {MINIMUM_ADMIN_PASSWORD_LENGTH} characters."
            )
        if len(password) > 256:
            raise ValueError("Password must contain 256 characters or fewer.")

        current = self.load()
        updated = SecureSettings(
            **{
                **asdict(current),
                "admin_password_hash": generate_password_hash(
                    password,
                    method="scrypt",
                ),
                "password_created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return self._save(updated)

    def verify_admin_password(self, password: str) -> bool:
        """Verify a candidate without ever exposing the stored hash to callers."""

        current = self.load()
        if not current.admin_password_hash:
            return False
        return check_password_hash(current.admin_password_hash, password)

    def save_verified_ai_key(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_GROQ_BASE_URL,
        model: str = DEFAULT_GROQ_MODEL,
    ) -> SecureSettings:
        """Persist a key only after the caller has successfully tested it."""

        current = self.load()
        updated = SecureSettings(
            **{
                **asdict(current),
                "ai_api_key": api_key,
                "ai_base_url": base_url,
                "ai_model": model,
                "ai_enabled": False,
                "ai_last_test_ok": True,
                "ai_last_test_at": datetime.now(timezone.utc).isoformat(),
                "ai_last_error": "",
            }
        )
        return self._save(updated)

    def record_ai_test(self, *, ok: bool, error: str = "") -> SecureSettings:
        """Record a test of the already-saved key without changing the key."""

        current = self.load()
        updated = SecureSettings(
            **{
                **asdict(current),
                "ai_enabled": current.ai_enabled if ok else False,
                "ai_last_test_ok": ok,
                "ai_last_test_at": datetime.now(timezone.utc).isoformat(),
                "ai_last_error": error[:500],
            }
        )
        return self._save(updated)

    def set_ai_enabled(self, enabled: bool) -> SecureSettings:
        """Persist Remote AI state, refusing to enable an unverified key."""

        current = self.load()
        if enabled and not current.ai_key_active:
            raise ValueError("A successfully tested API key is required before enabling Remote AI.")

        updated = SecureSettings(**{**asdict(current), "ai_enabled": enabled})
        return self._save(updated)

    def remove_ai_key(self) -> SecureSettings:
        """Remove the API key and forcibly disable all remote AI requests."""

        current = self.load()
        updated = SecureSettings(
            **{
                **asdict(current),
                "ai_api_key": "",
                "ai_enabled": False,
                "ai_last_test_ok": False,
                "ai_last_test_at": "",
                "ai_last_error": "",
            }
        )
        return self._save(updated)
