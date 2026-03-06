from __future__ import annotations

import fnmatch
import hashlib
import io
import os
import tarfile
import tempfile

from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


DEFAULT_BOOTSTRAP_ARCHIVE_NAME = "google_api_profile.bin"
_ARCHIVE_MAGIC = b"WBUPRF1\0"
_KEY_LEN = 32
_NONCE_LEN = 12
_SALT_LEN = 16
_PBKDF2_ROUNDS = 200_000
_ALLOWED_EXACT_PATHS = {
    Path("google_cookies.json"),
    Path("Local State"),
    Path("Last Version"),
    Path("First Run"),
    Path("Variations"),
    Path("Default/Bookmarks"),
    Path("Default/Cookies"),
    Path("Default/Favicons"),
    Path("Default/Preferences"),
    Path("Default/Safe Browsing Cookies"),
}
_ALLOWED_PREFIX_PATHS = {
    Path("Default/Local Storage"),
    Path("Default/Session Storage"),
    Path("Default/SharedStorage"),
    Path("Default/WebStorage"),
}
_EXCLUDED_DIR_NAMES = {
    "blob_storage",
    "Cache",
    "component_crx_cache",
    "Code Cache",
    "Crashpad",
    "DawnCache",
    "GPUCache",
    "GrShaderCache",
    "OnDeviceHeadSuggestModel",
    "ShaderCache",
    "WidevineCdm",
}
_EXCLUDED_FILE_PATTERNS = {
    "*.lock",
    "*.log",
    "*.tmp",
    "BrowserMetrics*",
    "Cookies-journal",
    "History",
    "History-journal",
    "LOCK",
    "Login Data",
    "Login Data For Account",
    "Login Data For Account-journal",
    "Login Data-journal",
    "Network Persistent State",
    "Secure Preferences",
    "Singleton*",
    "Top Sites",
    "Top Sites-journal",
    "Visited Links",
    "Web Data",
    "Web Data-journal",
}


def _matches_allowed_prefix(relative_path: Path) -> bool:
    for prefix in _ALLOWED_PREFIX_PATHS:
        if relative_path == prefix or prefix in relative_path.parents:
            return True
    return False


def _can_contain_allowed_descendants(relative_path: Path) -> bool:
    for allowed in _ALLOWED_EXACT_PATHS | _ALLOWED_PREFIX_PATHS:
        if relative_path == allowed or relative_path in allowed.parents:
            return True
    return False


def _derive_key(secret: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        secret.encode("utf-8"),
        salt,
        _PBKDF2_ROUNDS,
        dklen=_KEY_LEN,
    )


def _encrypt_bytes(plaintext: bytes, secret: str) -> bytes:
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive_key(secret, salt)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _ARCHIVE_MAGIC)
    return _ARCHIVE_MAGIC + salt + nonce + ciphertext


def _decrypt_bytes(payload: bytes, secret: str) -> bytes:
    if len(payload) <= len(_ARCHIVE_MAGIC) + _SALT_LEN + _NONCE_LEN:
        raise ValueError("Bootstrap archive payload is truncated")
    if not payload.startswith(_ARCHIVE_MAGIC):
        raise ValueError("Bootstrap archive header is invalid")

    offset = len(_ARCHIVE_MAGIC)
    salt = payload[offset : offset + _SALT_LEN]
    offset += _SALT_LEN
    nonce = payload[offset : offset + _NONCE_LEN]
    offset += _NONCE_LEN
    ciphertext = payload[offset:]
    key = _derive_key(secret, salt)
    return AESGCM(key).decrypt(nonce, ciphertext, _ARCHIVE_MAGIC)


def _should_skip_path(relative_path: Path, is_dir: bool) -> bool:
    name = relative_path.name
    if is_dir and name in _EXCLUDED_DIR_NAMES:
        return True
    if any(fnmatch.fnmatch(name, pattern) for pattern in _EXCLUDED_FILE_PATTERNS):
        return True
    if is_dir:
        return not _can_contain_allowed_descendants(relative_path)
    return relative_path not in _ALLOWED_EXACT_PATHS and not _matches_allowed_prefix(
        relative_path
    )


def _iter_profile_files(source_dir: Path):
    for root, dirnames, filenames in os.walk(source_dir):
        root_path = Path(root)
        relative_root = root_path.relative_to(source_dir)
        dirnames[:] = [
            name
            for name in dirnames
            if not _should_skip_path(relative_root / name, is_dir=True)
        ]
        for filename in filenames:
            relative_path = (
                relative_root / filename
                if str(relative_root) != "."
                else Path(filename)
            )
            if _should_skip_path(relative_path, is_dir=False):
                continue
            yield root_path / filename, relative_path


def create_encrypted_profile_archive(
    source_dir: str | Path, output_path: str | Path, secret: str
) -> bool:
    source_dir = Path(source_dir).expanduser()
    output_path = Path(output_path).expanduser()
    if not secret.strip():
        raise ValueError("Bootstrap archive secret is required")
    if not source_dir.exists() or not any(source_dir.iterdir()):
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        with tarfile.open(temp_path, mode="w:gz") as archive:
            for file_path, relative_path in _iter_profile_files(source_dir):
                archive.add(
                    file_path, arcname=relative_path.as_posix(), recursive=False
                )

        plaintext = temp_path.read_bytes()
        output_path.write_bytes(_encrypt_bytes(plaintext, secret))
        return True
    finally:
        temp_path.unlink(missing_ok=True)


def _validate_archive_member(member_name: str, target_dir: Path):
    resolved_target = target_dir.resolve()
    candidate = (target_dir / member_name).resolve()
    if candidate != resolved_target and resolved_target not in candidate.parents:
        raise ValueError(f"Bootstrap archive contains unsafe path: {member_name}")


def restore_encrypted_profile_archive(
    archive_path: str | Path, target_dir: str | Path, secret: str
) -> None:
    archive_path = Path(archive_path).expanduser()
    target_dir = Path(target_dir).expanduser()
    if not secret.strip():
        raise ValueError("Bootstrap archive secret is required")
    if not archive_path.exists():
        raise FileNotFoundError(archive_path)

    plaintext = _decrypt_bytes(archive_path.read_bytes(), secret)
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(plaintext), mode="r:gz") as archive:
        for member in archive.getmembers():
            _validate_archive_member(member.name, target_dir)
        archive.extractall(path=target_dir)


def rewrite_encrypted_profile_archive(
    source_archive_path: str | Path,
    target_archive_path: str | Path,
    source_secret: str,
    target_secret: str,
) -> bool:
    with tempfile.TemporaryDirectory(prefix="webu-profile-rewrite-") as tempdir:
        restored_dir = Path(tempdir) / "profile"
        restore_encrypted_profile_archive(
            source_archive_path, restored_dir, source_secret
        )
        return create_encrypted_profile_archive(
            restored_dir, target_archive_path, target_secret
        )
