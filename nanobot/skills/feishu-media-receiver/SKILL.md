---
name: feishu-media-receiver
description: Automatically receive and download media files (images, videos, documents) sent from Feishu. Use when the agent needs to handle file transfers from Feishu messages, including: (1) Downloading images from Feishu, (2) Downloading videos from Feishu, (3) Downloading documents from Feishu, (4) Organizing downloaded files by date and type, (5) Recording file metadata
---

# Feishu Media Receiver

Automatically receive and organize media files sent from Feishu.

## Quick Start

When a user sends media (image, video, file) via Feishu:
1. The file is automatically downloaded to `workspace/media/`
2. Files are renamed with date prefix: `YYYY-MM-DD_originalname.ext`
3. Metadata is recorded in `workspace/media/media_log.json`

## File Organization

```
workspace/media/
├── images/        # Downloaded images
├── videos/        # Downloaded videos
├── documents/     # Downloaded documents
└── media_log.json # Download history
```

## Supported File Types

| Type      | Extensions                          |
|-----------|-------------------------------------|
| Images    | .jpg, .png, .gif, .webp, .bmp       |
| Videos    | .mp4, .webm, .mov, .avi             |
| Documents | .pdf, .doc, .docx, .xlsx, .txt, .zip|

## Scripts

### `download_media.py`

Download media from Feishu and organize by type.

Usage:
```bash
python scripts/download_media.py <file_key> <msg_type> <mime_type> <output_dir>
```

Parameters:
- `file_key`: Feishu file key from message
- `msg_type`: Message type (image, video, file)
- `mime_type`: MIME type from Feishu API
- `output_dir`: Output directory (default: workspace/media)

## Integration with Feishu

This skill works with the feishu.py channel adapter. When a message contains media:
1. feishu.py calls `_download_file()` to download the file
2. File is saved to appropriate subdirectory
3. Metadata is logged

## Troubleshooting

**Files not downloading:**
- Check `restrict_to_workspace` setting in feishu.py
- Verify Feishu bot has `im:resource` permission
- Check media directory permissions

**Wrong file extension:**
- MIME type mapping in `_get_extension()` method
- Add new MIME types to the mapping if needed

## Special Folders

For specific use cases, media can be directed to custom folders:
- Baby photos: `workspace/baby_photos/`
- Work documents: `workspace/documents/`
- Personal files: `workspace/personal/`