"""SSH/SFTP helpers for Raspberry Pi upload workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import paramiko
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    paramiko = None


SSH_USERNAME = "pi"
SSH_PASSWORD = "raspberry"
UPLOAD_DIRECTORY = "/home/pi"
SSH_PORT = 22


@dataclass(frozen=True)
class UploadResult:
    local_path: Path
    remote_path: str
    mode: int


def verify_connection(
    host: str,
    username: str = SSH_USERNAME,
    password: str = SSH_PASSWORD,
    port: int = SSH_PORT,
    timeout: float = 8,
) -> None:
    client = connect_ssh(host, username, password, port, timeout)
    client.close()


def upload_file(
    host: str,
    file_path: str | Path,
    remote_directory: str = UPLOAD_DIRECTORY,
    username: str = SSH_USERNAME,
    password: str = SSH_PASSWORD,
    port: int = SSH_PORT,
    timeout: float = 8,
) -> UploadResult:
    local_path = Path(file_path)
    if not local_path.is_file():
        raise FileNotFoundError(f"File not found: {local_path}")

    remote_path = f"{remote_directory.rstrip('/')}/{local_path.name}"
    mode = local_path.stat().st_mode & 0o777

    client = connect_ssh(host, username, password, port, timeout)
    try:
        with client.open_sftp() as sftp:
            sftp.put(str(local_path), remote_path)
            sftp.chmod(remote_path, mode)
    finally:
        client.close()

    return UploadResult(local_path=local_path, remote_path=remote_path, mode=mode)


def connect_ssh(
    host: str,
    username: str = SSH_USERNAME,
    password: str = SSH_PASSWORD,
    port: int = SSH_PORT,
    timeout: float = 8,
):
    if paramiko is None:
        raise RuntimeError(
            "Missing dependency: paramiko. Install with: python -m pip install -r requirements.txt"
        )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        host,
        port=port,
        username=username,
        password=password,
        timeout=timeout,
        auth_timeout=timeout,
        banner_timeout=timeout,
        look_for_keys=False,
        allow_agent=False,
    )
    return client
