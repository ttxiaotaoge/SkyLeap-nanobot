"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""

import asyncio
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FeishuConfig

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateFileRequest,
        CreateFileRequestBody,
        CreateImageRequest,
        CreateImageRequestBody,
        CreateMessageRequest,
        CreateMessageRequestBody,
        CreateMessageReactionRequest,
        CreateMessageReactionRequestBody,
        Emoji,
        GetMessageResourceRequest,
        P2ImMessageReceiveV1,
    )
    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    lark = None
    Emoji = None
    GetMessageResourceRequest = None
    CreateImageRequest = None
    CreateFileRequest = None

# Message type display mapping
MSG_TYPE_MAP = {
    "image": "[image]",
    "audio": "[audio]",
    "file": "[file]",
    "sticker": "[sticker]",
}


class FeishuChannel(BaseChannel):
    """
    Feishu/Lark channel using WebSocket long connection.
    
    Uses WebSocket to receive events - no public IP or webhook required.
    
    Requires:
    - App ID and App Secret from Feishu Open Platform
    - Bot capability enabled
    - Event subscription enabled (im.message.receive_v1)
    """
    
    name = "feishu"
    
    def __init__(self, config: FeishuConfig, bus: MessageBus, workspace: Path | None = None):
        super().__init__(config, bus)
        self.config: FeishuConfig = config
        self._client: Any = None
        self._ws_client: Any = None
        self._ws_thread: threading.Thread | None = None
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()  # Ordered dedup cache
        self._loop: asyncio.AbstractEventLoop | None = None
        self._workspace = workspace or Path.cwd()  # Use provided workspace or current directory
    
    async def start(self) -> None:
        """Start the Feishu bot with WebSocket long connection."""
        if not FEISHU_AVAILABLE:
            logger.error("Feishu SDK not installed. Run: pip install lark-oapi")
            return
        
        if not self.config.app_id or not self.config.app_secret:
            logger.error("Feishu app_id and app_secret not configured")
            return
        
        self._running = True
        self._loop = asyncio.get_running_loop()
        
        # Create Lark client for sending messages
        self._client = lark.Client.builder() \
            .app_id(self.config.app_id) \
            .app_secret(self.config.app_secret) \
            .log_level(lark.LogLevel.INFO) \
            .build()
        
        # Create event handler (only register message receive, ignore other events)
        event_handler = lark.EventDispatcherHandler.builder(
            self.config.encrypt_key or "",
            self.config.verification_token or "",
        ).register_p2_im_message_receive_v1(
            self._on_message_sync
        ).build()
        
        # Create WebSocket client for long connection
        self._ws_client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO
        )
        
        # Start WebSocket client in a separate thread
        def run_ws():
            try:
                self._ws_client.start()
            except Exception as e:
                logger.error(f"Feishu WebSocket error: {e}")
        
        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()
        
        logger.info("Feishu bot started with WebSocket long connection")
        logger.info("No public IP required - using WebSocket to receive events")
        
        # Keep running until stopped
        while self._running:
            await asyncio.sleep(1)
    
    async def stop(self) -> None:
        """Stop the Feishu bot."""
        self._running = False
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception as e:
                logger.warning(f"Error stopping WebSocket client: {e}")
        logger.info("Feishu bot stopped")
    
    def _add_reaction_sync(self, message_id: str, emoji_type: str) -> None:
        """Sync helper for adding reaction (runs in thread pool)."""
        try:
            request = CreateMessageReactionRequest.builder() \
                .message_id(message_id) \
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                    .build()
                ).build()
            
            response = self._client.im.v1.message_reaction.create(request)
            
            if not response.success():
                logger.warning(f"Failed to add reaction: code={response.code}, msg={response.msg}")
            else:
                logger.debug(f"Added {emoji_type} reaction to message {message_id}")
        except Exception as e:
            logger.warning(f"Error adding reaction: {e}")

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """
        Add a reaction emoji to a message (non-blocking).
        
        Common emoji types: THUMBSUP, OK, EYES, DONE, OnIt, HEART
        """
        if not self._client or not Emoji:
            return
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._add_reaction_sync, message_id, emoji_type)
    
    def _get_extension(self, msg_type: str, mime_type: str | None = None) -> str:
        """Get file extension based on message type and MIME type."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "image/webp": ".webp", "image/bmp": ".bmp",
                "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/ogg": ".ogg",
                "audio/wav": ".wav", "audio/x-wav": ".wav",
                "video/mp4": ".mp4", "video/webm": ".webm",
                "application/pdf": ".pdf",
                "application/msword": ".doc",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                "application/vnd.ms-excel": ".xls",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                "application/vnd.ms-powerpoint": ".ppt",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                "text/plain": ".txt",
                "application/zip": ".zip",
                "application/x-rar-compressed": ".rar",
                "application/octet-stream": ".bin",  # Binary data
            }
            if mime_type in ext_map:
                return ext_map[mime_type]
        
        type_map = {
            "image": ".jpg",
            "file": ".bin",  # Default to .bin for unknown file types
            "audio": ".mp3",
            "video": ".mp4",
            "media": ".bin",
        }
        return type_map.get(msg_type, ".bin")
    
    async def _download_file(self, file_key: str, msg_type: str, message_id: str) -> str | None:
        """
        Download file from Feishu using file_key.
        
        Args:
            file_key: The file key from Feishu message content
            msg_type: The message type (image, file, audio, video)
            message_id: The message ID for API request
            
        Returns:
            Local file path if successful, None otherwise
        """
        if not self._client or not GetMessageResourceRequest:
            logger.warning("Feishu client or GetMessageResourceRequest not available")
            return None
        
        try:
            # Build request to get file resource
            request = GetMessageResourceRequest.builder() \
                .message_id(message_id) \
                .file_key(file_key) \
                .type(msg_type) \
                .build()
            
            # Execute request in thread pool (blocking I/O)
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, self._client.im.v1.message_resource.get, request)
            
            if not response.success():
                logger.warning(
                    f"Failed to get file resource: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                return None
            
            # Get file content
            file_content = response.file
            if not file_content:
                logger.warning("File content is empty")
                return None
            
            # Read bytes from BytesIO object
            if hasattr(file_content, 'read'):
                file_bytes = file_content.read()
            else:
                file_bytes = file_content
            
            # Determine file extension
            # Try to get mime_type from response data
            mime_type = None
            file_name = None
            if hasattr(response, 'data') and response.data:
                mime_type = getattr(response.data, 'mime_type', None)
                file_name = getattr(response.data, 'file_name', None)
            
            # Try to extract extension from file_name first
            ext = ""
            if file_name:
                ext = Path(file_name).suffix
                logger.debug(f"Got extension from file_name: {ext}")
            
            # If no extension from file_name, try mime_type
            if not ext:
                ext = self._get_extension(msg_type, mime_type)
            
            # Create media directory in workspace (so AI can access it even with restrict_to_workspace)
            media_dir = self._workspace / "media"
            media_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate file path - use file_name if available, otherwise use file_key
            if file_name:
                # Sanitize file name to avoid path traversal
                safe_name = "".join(c for c in file_name if c.isalnum() or c in '._-')
                file_path = media_dir / safe_name
            else:
                file_path = media_dir / f"{file_key[:16]}{ext}"
            
            # Write file content
            with open(file_path, 'wb') as f:
                f.write(file_bytes)
            
            logger.info(f"Downloaded {msg_type} file to {file_path} (mime_type: {mime_type}, file_name: {file_name})")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Error downloading file from Feishu: {e}")
            return None
    
    def _upload_image_sync(self, file_path: str) -> str | None:
        """
        Sync helper for uploading image to Feishu.
        
        Args:
            file_path: Local path to the image file
            
        Returns:
            Image key if successful, None otherwise
        """
        if not self._client or not CreateImageRequest:
            logger.warning("Feishu client or CreateImageRequest not available")
            return None
        
        try:
            # Check if file exists
            from pathlib import Path
            path = Path(file_path)
            if not path.exists():
                logger.error(f"Image file does not exist: {file_path}")
                return None
            
            # Check file size
            file_size = path.stat().st_size
            logger.info(f"Uploading image: {file_path}, size: {file_size} bytes")
            
            if file_size == 0:
                logger.error(f"Image file is empty: {file_path}")
                return None
            
            if file_size > 10 * 1024 * 1024:  # 10MB limit per Feishu API docs
                logger.error(f"Image file too large: {file_size} bytes (max 10MB)")
                return None
            
            # Read file content
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Check if content was read
            if not file_content:
                logger.error(f"Failed to read file content: {file_path}")
                return None
            
            # Log file header (first 8 bytes) to detect format
            header = file_content[:8].hex()
            logger.info(f"File header (hex): {header}")
            
            # Detect actual image format from magic numbers
            magic_numbers = {
                b'\xff\xd8\xff': 'JPEG',
                b'\x89PNG\r\n\x1a\n': 'PNG',
                b'GIF87a': 'GIF87a',
                b'GIF89a': 'GIF89a',
                b'RIFF': 'WEBP',
                b'BM': 'BMP',
            }
            
            detected_format = None
            for magic, fmt in magic_numbers.items():
                if file_content.startswith(magic):
                    detected_format = fmt
                    break
            
            if detected_format:
                logger.info(f"Detected image format: {detected_format}")
            else:
                logger.warning(f"Unknown image format, header: {header}")
            
            # Build request to upload image
            # image_type: "message" for chat messages, "avatar" for user avatars
            # Use BytesIO to wrap the file content as required by lark-oapi SDK
            from io import BytesIO
            
            image_data = BytesIO(file_content)
            image_data.name = path.name  # Set filename with extension
            
            request = CreateImageRequest.builder() \
                .request_body(
                    CreateImageRequestBody.builder()
                    .image_type("message")
                    .image(image_data)
                    .build()
                ).build()
            
            logger.info(f"Uploading with BytesIO wrapper, filename: {path.name}")
            
            response = self._client.im.v1.image.create(request)
            
            if not response.success():
                logger.error(
                    f"Failed to upload image: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                logger.error(f"Image details - path: {file_path}, size: {file_size} bytes, "
                           f"detected_format: {detected_format}, header: {header}")
                return None
            
            image_key = response.data.image_key
            logger.info(f"Uploaded image to Feishu: {image_key}")
            return image_key
            
        except Exception as e:
            logger.error(f"Error uploading image to Feishu: {e}")
            return None
    
    def _upload_file_sync(self, file_path: str) -> str | None:
        """
        Sync helper for uploading file to Feishu.
        
        Args:
            file_path: Local path to the file
            
        Returns:
            File key if successful, None otherwise
        """
        if not self._client or not CreateFileRequest:
            logger.warning("Feishu client or CreateFileRequest not available")
            return None
        
        try:
            # Check if file exists
            path = Path(file_path)
            if not path.exists():
                logger.error(f"File does not exist: {file_path}")
                return None
            
            # Check file size
            file_size = path.stat().st_size
            logger.info(f"Uploading file: {file_path}, size: {file_size} bytes")
            
            if file_size == 0:
                logger.error(f"File is empty: {file_path}")
                return None
            
            if file_size > 30 * 1024 * 1024:  # 30MB limit per Feishu API docs
                logger.error(f"File too large: {file_size} bytes (max 30MB)")
                return None
            
            # Read file content
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            # Check if content was read
            if not file_content:
                logger.error(f"Failed to read file content: {file_path}")
                return None
            
            # Get file name from path
            file_name = path.name
            
            # Determine file type based on extension
            # According to Feishu API docs, file_type must be one of: opus, mp4, pdf, doc, xls
            ext = path.suffix.lower()
            
            # Map file extensions to Feishu file_type values
            ext_to_type = {
                # Audio files (must be OPUS format for Feishu)
                '.opus': 'opus',
                # Video files
                '.mp4': 'mp4',
                # Document files
                '.pdf': 'pdf',
                '.doc': 'doc',
                '.docx': 'doc',
                '.xls': 'xls',
                '.xlsx': 'xls',
            }
            
            # Get file_type from extension mapping
            file_type = ext_to_type.get(ext, 'file')
            
            # Note: For audio files other than OPUS, they need to be converted first
            # For now, we'll use 'file' type for unsupported formats
            if ext in {'.mp3', '.m4a', '.ogg', '.wav', '.flac', '.aac', '.webm', '.mov', '.avi', '.mkv'}:
                logger.warning(f"File type '{ext}' is not directly supported by Feishu API. "
                             f"Audio files should be OPUS format, video files should be MP4 format. "
                             f"Using 'file' type instead.")
                file_type = 'file'
            
            logger.info(f"File type: {file_type}, extension: {ext}")
            
            # Use BytesIO to wrap the file content as required by lark-oapi SDK
            from io import BytesIO
            file_data = BytesIO(file_content)
            file_data.name = file_name  # Set filename with extension
            
            # Build request to upload file
            request = CreateFileRequest.builder() \
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_type(file_type)
                    .file_name(file_name)
                    .file(file_data)
                    .build()
                ).build()
            
            logger.info(f"Uploading with BytesIO wrapper, filename: {file_name}, type: {file_type}")
            
            response = self._client.im.v1.file.create(request)
            
            if not response.success():
                logger.error(
                    f"Failed to upload file: code={response.code}, "
                    f"msg={response.msg}, log_id={response.get_log_id()}"
                )
                logger.error(f"File details - path: {file_path}, size: {file_size} bytes, "
                           f"type: {file_type}, extension: {ext}")
                return None
            
            file_key = response.data.file_key
            logger.info(f"Uploaded file to Feishu: {file_key}")
            return file_key
            
        except Exception as e:
            logger.error(f"Error uploading file to Feishu: {e}")
            return None
    
    async def _upload_media(self, file_path: str) -> tuple[str, str] | None:
        """
        Upload media file to Feishu.
        
        Args:
            file_path: Local path to the media file
            
        Returns:
            Tuple of (file_key, msg_type) if successful, None otherwise
        """
        # Determine file type based on extension
        ext = Path(file_path).suffix.lower()
        image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        
        loop = asyncio.get_running_loop()
        
        if ext in image_exts:
            # Upload as image
            file_key = await loop.run_in_executor(None, self._upload_image_sync, file_path)
            if file_key:
                return (file_key, "image")
        else:
            # Upload as file
            file_key = await loop.run_in_executor(None, self._upload_file_sync, file_path)
            if file_key:
                return (file_key, "file")
        
        return None
    
    # Regex to match markdown tables (header + separator + data rows)
    _TABLE_RE = re.compile(
        r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
        re.MULTILINE,
    )

    @staticmethod
    def _parse_md_table(table_text: str) -> dict | None:
        """Parse a markdown table into a Feishu table element."""
        lines = [l.strip() for l in table_text.strip().split("\n") if l.strip()]
        if len(lines) < 3:
            return None
        split = lambda l: [c.strip() for c in l.strip("|").split("|")]
        headers = split(lines[0])
        rows = [split(l) for l in lines[2:]]
        columns = [{"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
                   for i, h in enumerate(headers)]
        return {
            "tag": "table",
            "page_size": len(rows) + 1,
            "columns": columns,
            "rows": [{f"c{i}": r[i] if i < len(r) else "" for i in range(len(headers))} for r in rows],
        }

    def _build_card_elements(self, content: str) -> list[dict]:
        """Split content into markdown + table elements for Feishu card."""
        elements, last_end = [], 0
        for m in self._TABLE_RE.finditer(content):
            before = content[last_end:m.start()].strip()
            if before:
                elements.append({"tag": "markdown", "content": before})
            elements.append(self._parse_md_table(m.group(1)) or {"tag": "markdown", "content": m.group(1)})
            last_end = m.end()
        remaining = content[last_end:].strip()
        if remaining:
            elements.append({"tag": "markdown", "content": remaining})
        return elements or [{"tag": "markdown", "content": content}]

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Feishu."""
        if not self._client:
            logger.warning("Feishu client not initialized")
            return
        
        try:
            # Determine receive_id_type based on chat_id format
            # open_id starts with "ou_", chat_id starts with "oc_"
            if msg.chat_id.startswith("oc_"):
                receive_id_type = "chat_id"
            else:
                receive_id_type = "open_id"
            
            # Handle media files first
            if msg.media:
                for media_path in msg.media:
                    # Upload media file to Feishu
                    result = await self._upload_media(media_path)
                    if result:
                        file_key, msg_type = result
                        
                        # Send media message
                        # Note: image messages use "image_key", file messages use "file_key"
                        if msg_type == "image":
                            media_content = json.dumps({"image_key": file_key})
                        else:
                            media_content = json.dumps({"file_key": file_key})
                        
                        request = CreateMessageRequest.builder() \
                            .receive_id_type(receive_id_type) \
                            .request_body(
                                CreateMessageRequestBody.builder()
                                .receive_id(msg.chat_id)
                                .msg_type(msg_type)
                                .content(media_content)
                                .build()
                            ).build()
                        
                        response = self._client.im.v1.message.create(request)
                        
                        if not response.success():
                            logger.error(
                                f"Failed to send Feishu media message: code={response.code}, "
                                f"msg={response.msg}, log_id={response.get_log_id()}"
                            )
                        else:
                            logger.debug(f"Feishu {msg_type} message sent to {msg.chat_id}")
            
            # Send text content if present
            if msg.content:
                # Build card with markdown + table support
                elements = self._build_card_elements(msg.content)
                card = {
                    "config": {"wide_screen_mode": True},
                    "elements": elements,
                }
                content = json.dumps(card, ensure_ascii=False)
                
                request = CreateMessageRequest.builder() \
                    .receive_id_type(receive_id_type) \
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(msg.chat_id)
                        .msg_type("interactive")
                        .content(content)
                        .build()
                    ).build()
                
                response = self._client.im.v1.message.create(request)
                
                if not response.success():
                    logger.error(
                        f"Failed to send Feishu message: code={response.code}, "
                        f"msg={response.msg}, log_id={response.get_log_id()}"
                    )
                else:
                    logger.debug(f"Feishu message sent to {msg.chat_id}")
                
        except Exception as e:
            logger.error(f"Error sending Feishu message: {e}")
    
    def _on_message_sync(self, data: "P2ImMessageReceiveV1") -> None:
        """
        Sync handler for incoming messages (called from WebSocket thread).
        Schedules async handling in the main event loop.
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)
    
    async def _on_message(self, data: "P2ImMessageReceiveV1") -> None:
        """Handle incoming message from Feishu."""
        try:
            event = data.event
            message = event.message
            sender = event.sender
            
            # Deduplication check
            message_id = message.message_id
            if message_id in self._processed_message_ids:
                return
            self._processed_message_ids[message_id] = None
            
            # Trim cache: keep most recent 500 when exceeds 1000
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)
            
            # Skip bot messages
            sender_type = sender.sender_type
            if sender_type == "bot":
                return
            
            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type  # "p2p" or "group"
            msg_type = message.message_type
            
            # Add reaction to indicate "seen"
            await self._add_reaction(message_id, "OK")
            
            # Parse message content and handle media files
            content_parts = []
            media_paths = []
            
            if msg_type == "text":
                try:
                    content = json.loads(message.content).get("text", "")
                    if content:
                        content_parts.append(content)
                except json.JSONDecodeError:
                    content = message.content or ""
                    if content:
                        content_parts.append(content)
            else:
                # Handle media files (image, file, audio, video)
                try:
                    content_data = json.loads(message.content)
                    
                    # Try different key names for file_key
                    file_key = content_data.get("file_key")
                    if not file_key and msg_type == "image":
                        # Image messages might use "image_key" instead
                        file_key = content_data.get("image_key")
                    
                    if file_key:
                        # Download the file
                        logger.info(f"Found file_key: {file_key[:16]}... for message {message_id}")
                        file_path = await self._download_file(file_key, msg_type, message_id)
                        if file_path:
                            media_paths.append(file_path)
                            content_parts.append(f"[{msg_type}: {file_path}]")
                            logger.info(f"Successfully downloaded {msg_type} to {file_path}")
                        else:
                            content_parts.append(f"[{msg_type}: download failed]")
                            logger.warning(f"Failed to download {msg_type} with file_key {file_key[:16]}...")
                    else:
                        # No file_key, just use placeholder
                        content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))
                        logger.warning(f"No file_key found in message content for type {msg_type}")
                        logger.debug(f"Message content: {message.content}")
                except json.JSONDecodeError:
                    content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))
                    logger.error(f"Failed to parse message content as JSON: {message.content[:200]}")
            
            # Check for caption or additional text
            if hasattr(message, 'content') and msg_type != "text":
                try:
                    content_data = json.loads(message.content)
                    # Some media types might have additional text fields
                    if "text" in content_data:
                        content_parts.append(content_data["text"])
                except (json.JSONDecodeError, AttributeError):
                    pass
            
            content = "\n".join(content_parts) if content_parts else "[empty message]"
            
            # Forward to message bus
            reply_to = chat_id if chat_type == "group" else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                media=media_paths if media_paths else None,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing Feishu message: {e}")
