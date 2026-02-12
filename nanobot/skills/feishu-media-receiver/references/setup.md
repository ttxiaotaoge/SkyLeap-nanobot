# Feishu Media Receiver - Setup Guide

## Configuration

### 1. Feishu Bot Permissions

Ensure your Feishu bot has the following permissions:
- `im:message` - Send and receive messages
- `im:resource` - Download files and images
- `im:file` - Upload files (if sending files back)

### 2. Workspace Directory Structure

Create the following directories:
```
workspace/
├── media/
│   ├── images/      # Downloaded images
│   ├── videos/      # Downloaded videos
│   ├── documents/   # Downloaded documents
│   └── audio/       # Downloaded audio
├── baby_photos/     # Baby photos (custom)
└── documents/       # Work documents (custom)
```

### 3. Feishu.py Configuration

In `feishu.py`, ensure these settings:

```python
# Enable file downloads
restrict_to_workspace = True  # Only download to workspace

# Media directory
media_dir = "workspace/media"

# Auto-organize files
auto_organize = True
```

## Integration with feishu.py

The `feishu.py` channel adapter should:
1. Detect media in incoming messages
2. Download to `workspace/media/`
3. Organize by type and date
4. Log metadata

## Testing

Send a test image to verify:
1. Image is downloaded to `workspace/media/images/`
2. File is renamed with date prefix
3. Entry appears in `media_log.json`

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Files not downloading | Check `im:resource` permission |
| Wrong file type | Verify MIME type mapping |
| Files in wrong folder | Check `get_subdir()` function |
| Duplicate filenames | Counter handles duplicates automatically |