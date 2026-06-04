#!/usr/bin/env python3
"""
Push image file(s) to an Android phone over USB using adb.

Drops the file into the phone's storage (default: /sdcard/Pictures/) and runs a
media-scanner broadcast so it shows up in the Gallery/Photos app immediately.

Requirements:
  - adb installed (`brew install android-platform-tools`)
  - Phone connected via USB with USB debugging enabled (Developer Options)
  - The "Allow USB debugging" prompt accepted on the phone

Pairs with tiktok_image_generator.py — generate an image, then push it here.

Usage (CLI):
    python phone_uploader.py cat.png
    python phone_uploader.py skyline.png --dest /sdcard/Download
    python phone_uploader.py *.png --serial 1A2B3C4D
    python phone_uploader.py img.png --dest /sdcard/DCIM/Camera

Usage (as a module):
    from phone_uploader import push_to_phone
    remote = push_to_phone("cat.png")
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional


# Pictures shows up in Gallery; Download is easier to find in a file manager.
DEFAULT_DEST = "/sdcard/Pictures"


class PhonePushError(Exception):
    """Raised when an adb push to the phone fails."""


def _run_adb(args: list[str], *, serial: Optional[str] = None, timeout: int = 120) -> str:
    """Run an adb command and return stdout. Raises PhonePushError on failure."""
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        raise PhonePushError(
            "adb not found. Install it with `brew install android-platform-tools`."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise PhonePushError(f"adb command timed out: {' '.join(cmd)}") from e

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise PhonePushError(f"adb {' '.join(args)} failed: {err}")
    return proc.stdout.strip()


def _list_devices() -> list[str]:
    """Return serials of connected, authorized devices."""
    out = _run_adb(["devices"])
    serials: list[str] = []
    for line in out.splitlines()[1:]:  # skip "List of devices attached"
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _ensure_device(serial: Optional[str]) -> str:
    """Resolve which device to use, or raise a helpful error."""
    serials = _list_devices()
    if not serials:
        raise PhonePushError(
            "No authorized Android device found. Check that:\n"
            "  - the phone is plugged in via USB,\n"
            "  - USB debugging is enabled in Developer Options,\n"
            "  - you accepted the 'Allow USB debugging' prompt on the phone.\n"
            "Run `adb devices` to verify."
        )
    if serial:
        if serial not in serials:
            raise PhonePushError(
                f"Device {serial!r} not connected. Available: {', '.join(serials)}"
            )
        return serial
    if len(serials) > 1:
        raise PhonePushError(
            f"Multiple devices connected: {', '.join(serials)}. "
            "Pass --serial to pick one."
        )
    return serials[0]


def push_to_phone(
    image_path: str,
    *,
    dest_dir: str = DEFAULT_DEST,
    serial: Optional[str] = None,
    scan_media: bool = True,
) -> str:
    """
    Push a single image to the phone and return its remote path.

    Args:
        image_path: Local image file to push.
        dest_dir: Remote directory on the phone (e.g. /sdcard/Pictures).
        serial: Target device serial. Auto-detected if only one is connected.
        scan_media: If True, trigger a media-scan broadcast so the file
            appears in the Gallery immediately.

    Returns:
        The remote path the file was written to.

    Raises:
        PhonePushError: On any failure.
    """
    path = Path(image_path)
    if not path.is_file():
        raise PhonePushError(f"File not found: {path}")

    target = _ensure_device(serial)
    remote = f"{dest_dir.rstrip('/')}/{path.name}"

    _run_adb(["push", str(path), remote], serial=target)

    if scan_media:
        # Ask Android's MediaScanner to index the new file so the Gallery sees it.
        _run_adb(
            [
                "shell",
                "am",
                "broadcast",
                "-a",
                "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                "-d",
                f"file://{remote}",
            ],
            serial=target,
        )

    return remote


def _cli() -> int:
    from env_loader import load_env
    load_env()

    parser = argparse.ArgumentParser(
        description="Push image file(s) to an Android phone over USB (adb)."
    )
    parser.add_argument("paths", nargs="+", help="Local image file path(s) to push")
    parser.add_argument(
        "--dest",
        default=DEFAULT_DEST,
        help=f"Remote directory on the phone (default: {DEFAULT_DEST})",
    )
    parser.add_argument(
        "--serial",
        default=None,
        help="Target device serial (required if multiple devices are connected)",
    )
    parser.add_argument(
        "--no-scan",
        action="store_true",
        help="Skip the media-scan broadcast (file won't auto-appear in Gallery)",
    )
    args = parser.parse_args()

    failed = 0
    for p in args.paths:
        try:
            remote = push_to_phone(
                p,
                dest_dir=args.dest,
                serial=args.serial,
                scan_media=not args.no_scan,
            )
            print(f"Pushed: {p} -> {remote}")
        except PhonePushError as e:
            print(f"Error pushing {p}: {e}", file=sys.stderr)
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_cli())
