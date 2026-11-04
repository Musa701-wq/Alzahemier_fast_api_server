import os
from typing import Iterable, Optional
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings
from app.core.logging import logger

ALLOWED_IMAGE_EXTENSIONS = tuple(ext.lower() for ext in settings.ALLOWED_EXTENSIONS)
MAX_FILE_SIZE_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


def get_file_extension(filename: str) -> str:
    """Extract normalized lowercase extension from filename (supporting .nii.gz)."""
    if not filename:
        return ""
    lower_name = filename.lower().strip()
    if lower_name.endswith(".nii.gz"):
        return ".nii.gz"
    _, ext = os.path.splitext(lower_name)
    return ext


def validate_file_extension(
    filename: str,
    allowed_extensions: Optional[Iterable[str]] = None,
) -> str:
    """
    Validate that the file has a supported MRI scan extension.

    Raises:
        HTTPException (400): If filename is missing or extension is unsupported.
    """
    if not filename or not filename.strip():
        logger.warning("MRI upload rejected: missing filename.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required for MRI scan validation.",
        )

    allowed = tuple(ext.lower() for ext in (allowed_extensions or ALLOWED_IMAGE_EXTENSIONS))
    ext = get_file_extension(filename)

    if not ext or ext not in allowed:
        logger.warning(f"Unsupported file extension '{ext}' for file '{filename}'.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file format '{ext or 'unknown'}'. "
                f"Allowed formats: {', '.join(allowed)}"
            ),
        )

    return ext


def validate_file_size(
    file_bytes: bytes,
    max_size_mb: Optional[int] = None,
) -> int:
    """
    Validate that the uploaded MRI payload is non-empty and within the maximum size limit.

    Raises:
        HTTPException (400): If file is empty.
        HTTPException (413): If file exceeds maximum allowed size.
    """
    size_bytes = len(file_bytes)
    if size_bytes == 0:
        logger.warning("MRI upload rejected: empty file payload.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded MRI file is empty.",
        )

    limit_mb = max_size_mb if max_size_mb is not None else settings.MAX_UPLOAD_SIZE_MB
    limit_bytes = limit_mb * 1024 * 1024

    if size_bytes > limit_bytes:
        size_mb = size_bytes / (1024 * 1024)
        logger.warning(f"MRI upload rejected: file size {size_mb:.2f}MB exceeds {limit_mb}MB limit.")
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File size ({size_mb:.2f} MB) exceeds maximum allowed limit of {limit_mb} MB.",
        )

    return size_bytes


async def validate_mri_upload(file: UploadFile) -> bytes:
    """
    Validate an incoming FastAPI UploadFile for extension and payload size,
    returning the raw bytes if valid.
    """
    validate_file_extension(file.filename or "")
    content = await file.read()
    validate_file_size(content)
    await file.seek(0)
    return content

