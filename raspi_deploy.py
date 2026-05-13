#!/usr/bin/env python3
"""Verify SSH access to a Raspberry Pi or upload a file to it."""

from __future__ import annotations

import argparse
import sys

from raspi_deploy_lib import (
    SSH_PASSWORD,
    SSH_TIMEOUT,
    SSH_USERNAME,
    UPLOAD_DIRECTORY,
    upload_file,
    verify_connection,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify SSH access to a Raspberry Pi or upload a file."
    )
    parser.add_argument("--host", required=True, help="Raspberry Pi IP address or hostname")
    parser.add_argument("--upload", help="local file to upload")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify SSH connection without uploading",
    )
    parser.add_argument(
        "--remote-dir",
        default=UPLOAD_DIRECTORY,
        help=f"remote upload directory (default: {UPLOAD_DIRECTORY})",
    )
    parser.add_argument(
        "--user",
        default=SSH_USERNAME,
        help=f"SSH username (default: {SSH_USERNAME})",
    )
    parser.add_argument(
        "--password",
        default=SSH_PASSWORD,
        help="SSH password (default: raspberry)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=SSH_TIMEOUT,
        help=f"SSH timeout in seconds (default: {SSH_TIMEOUT:g})",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        print("--timeout must be greater than zero", file=sys.stderr)
        return 2
    if not args.verify and not args.upload:
        print("Pass --verify or --upload PATH.", file=sys.stderr)
        return 2

    try:
        if args.verify:
            verify_connection(
                args.host,
                username=args.user,
                password=args.password,
                timeout=args.timeout,
            )
            print(f"SSH connection verified for {args.host}.")

        if args.upload:
            result = upload_file(
                args.host,
                args.upload,
                remote_directory=args.remote_dir,
                username=args.user,
                password=args.password,
                timeout=args.timeout,
            )
            print(
                f"Uploaded {result.local_path.name} to {args.host}:{result.remote_path} "
                f"with mode {result.mode:o}."
            )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
