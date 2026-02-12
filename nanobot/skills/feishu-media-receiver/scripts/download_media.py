#!/usr/bin/env python3
"""
Feishu Media Downloader
Download and organize media files from Feishu
"""

import os
import sys
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

# MIME type to extension mapping
MIME_EXTENSIONS = {
    # Images
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    # Videos
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    # Documents
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/x-rar-compressed": ".rar",
}

# Type to subdirectory mapping
TYPE_SUBDIRS = {
    "image": "images",
    "video": "videos",
    "file": "documents",
    "audio": "audio",
}


def get_extension(mime_type: str, default: str = ".bin") -> str:
    """Get file extension from MIME type"""
    return MIME_EXTENSIONS.get(mime_type.lower(), default)


def get_subdir(msg_type: str) -> str:
    """Get subdirectory for message type"""
    return TYPE_SUBDIRS.get(msg_type.lower(), "documents")


def organize_file(source_path: str, msg_type: str, custom_dir: Optional[str] = None) -> str:
    """
    Organize downloaded file by type and date

    Args:
        source_path: Path to downloaded file
        msg_type: Message type (image, video, file)
        custom_dir: Custom directory override

    Returns:
        Path to organized file
    """
    source = Path(source_path)

    # Determine target directory
    if custom_dir:
        target_dir = Path(custom_dir)
    else:
        base_dir = Path("workspace/media")
        subdir = get_subdir(msg_type)
        target_dir = base_dir / subdir

    # Create directory if needed
    target_dir.mkdir(parents=True, exist_ok=True)

    # Generate new filename with date prefix
    today = datetime.now().strftime("%Y-%m-%d")
    ext = source.suffix
    new_name = f"{today}_{source.name}"
    target_path = target_dir / new_name

    # Handle duplicates
    counter = 1
    while target_path.exists():
        stem = source.stem
        new_name = f"{today}_{stem}_{counter}{ext}"
        target_path = target_dir / new_name
        counter += 1

    # Move file
    shutil.move(str(source), str(target_path))

    return str(target_path)


def log_download(file_path: str, msg_type: str, metadata: dict, log_file: str = "workspace/media/media_log.json"):
    """
    Log download information

    Args:
        file_path: Path to downloaded file
        msg_type: Message type
        metadata: Additional metadata (file_key, mime_type, etc.)
        log_file: Path to log file
    """
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing log
    if log_path.exists():
        with open(log_path, "r", encoding="utf-8") as f:
            logs = json.load(f)
    else:
        logs = []

    # Add new entry
    entry = {
        "timestamp": datetime.now().isoformat(),
        "file_path": file_path,
        "msg_type": msg_type,
        **metadata
    }
    logs.append(entry)

    # Save log
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)


def main():
    """Main entry point for manual testing"""
    if len(sys.argv) < 5:
        print("Usage: python download_media.py <file_key> <msg_type> <mime_type> <output_dir> [--custom-dir <path>]")
        sys.exit(1)

    file_key = sys.argv[1]
    msg_type = sys.argv[2]
    mime_type = sys.argv[3]
    output_dir = sys.argv[4]

    # Check for custom directory
    custom_dir = None
    if "--custom-dir" in sys.argv:
        idx = sys.argv.index("--custom-dir")
        if idx + 1 < len(sys.argv):
            custom_dir = sys.argv[idx + 1]

    print(f"Downloading media from Feishu...")
    print(f"  File Key: {file_key}")
    print(f"  Type: {msg_type}")
    print(f"  MIME: {mime_type}")
    print(f"  Output: {output_dir}")
    if custom_dir:
        print(f"  Custom Dir: {custom_dir}")

    # Note: This is a placeholder for actual Feishu API download
    # In production, feishu.py's _download_file() handles the actual download
    # This script is for organization and logging after download

    print("\nFor actual downloads, media is handled by feishu.py channel adapter.")
    print("This script can be used to reorganize existing downloaded files.")


if __name__ == "__main__":
    main()