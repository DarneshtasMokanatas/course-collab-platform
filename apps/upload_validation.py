import hashlib
import unicodedata
import zipfile
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.utils.text import get_valid_filename

MIME_TYPES_BY_EXTENSION = {
    "csv": "text/csv",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "pdf": "application/pdf",
    "png": "image/png",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "txt": "text/plain",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "zip": "application/zip",
}
ZIP_MEMBER_PREFIX = {
    "docx": "word/",
    "pptx": "ppt/",
    "xlsx": "xl/",
}
OOXML_MAIN_PART = {
    "docx": (
        "word/document.xml",
        b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    ),
    "pptx": (
        "ppt/presentation.xml",
        b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    ),
    "xlsx": (
        "xl/workbook.xml",
        b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    ),
}


def sanitize_filename(name):
    normalized = unicodedata.normalize("NFKC", str(name)).replace("\\", "/")
    basename = PurePosixPath(normalized).name
    basename = "".join(character for character in basename if character.isprintable())
    basename = basename.strip().lstrip(".")
    try:
        safe_name = get_valid_filename(basename)
    except ValidationError as error:
        raise ValidationError("The upload filename is invalid.") from error
    if not safe_name:
        raise ValidationError("The upload filename is invalid.")
    return safe_name[-255:]


def _detected_content_type(upload, extension):
    upload.seek(0)
    header = upload.read(16)
    upload.seek(0)
    if extension == "pdf" and header.startswith(b"%PDF-"):
        return MIME_TYPES_BY_EXTENSION[extension]
    if extension == "png" and header.startswith(b"\x89PNG\r\n\x1a\n"):
        return MIME_TYPES_BY_EXTENSION[extension]
    if extension in {"jpg", "jpeg"} and header.startswith(b"\xff\xd8\xff"):
        return MIME_TYPES_BY_EXTENSION[extension]
    if extension in {"doc", "ppt", "xls"}:
        raise ValidationError(
            "Legacy Office uploads cannot be validated safely; use an OOXML format."
        )
    if extension in {"zip", "docx", "pptx", "xlsx"}:
        try:
            with zipfile.ZipFile(upload) as archive:
                names = archive.namelist()
        except (OSError, zipfile.BadZipFile) as error:
            raise ValidationError("The uploaded archive is not valid.") from error
        finally:
            upload.seek(0)
        if extension in ZIP_MEMBER_PREFIX and not (
            "[Content_Types].xml" in names and OOXML_MAIN_PART[extension][0] in names
        ):
            raise ValidationError(
                "The uploaded file content does not match its extension."
            )
        if extension in OOXML_MAIN_PART:
            try:
                with zipfile.ZipFile(upload) as archive:
                    content_types = archive.read("[Content_Types].xml")
            except (KeyError, OSError, zipfile.BadZipFile) as error:
                raise ValidationError(
                    "The uploaded file content does not match its extension."
                ) from error
            finally:
                upload.seek(0)
            if OOXML_MAIN_PART[extension][1] not in content_types:
                raise ValidationError(
                    "The uploaded file content does not match its extension."
                )
        return MIME_TYPES_BY_EXTENSION[extension]
    if extension in {"txt", "csv"}:
        upload.seek(0)
        sample = upload.read(4096)
        upload.seek(0)
        if b"\x00" not in sample:
            try:
                sample.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                return MIME_TYPES_BY_EXTENSION[extension]
    raise ValidationError("The uploaded file content does not match its extension.")


def validated_upload_metadata(*, upload, allowed_extensions, max_upload_bytes):
    filename = sanitize_filename(upload.name)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in allowed_extensions or extension not in MIME_TYPES_BY_EXTENSION:
        raise ValidationError("This file type is not allowed.")
    if upload.size <= 0 or upload.size > max_upload_bytes:
        raise ValidationError("This file does not meet the upload size limit.")

    content_type = _detected_content_type(upload, extension)
    claimed_type = (upload.content_type or "").partition(";")[0].strip().lower()
    if claimed_type and claimed_type not in {
        content_type,
        "application/octet-stream",
        "application/zip" if extension in ZIP_MEMBER_PREFIX else content_type,
    }:
        raise ValidationError(
            "The uploaded file content type does not match its extension."
        )

    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return filename, content_type, upload.size, digest.hexdigest()
