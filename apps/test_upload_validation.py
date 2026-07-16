from io import BytesIO
from zipfile import ZipFile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from .upload_validation import validated_upload_metadata


def ooxml_upload(name, main_part, content_type):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            f'<Types><Override ContentType="{content_type}"/></Types>',
        )
        archive.writestr(main_part, "<document/>")
    return SimpleUploadedFile(
        name,
        buffer.getvalue(),
        content_type="application/zip",
    )


class UploadContentDetectionTests(SimpleTestCase):
    def test_ooxml_type_must_match_extension(self):
        valid = ooxml_upload(
            "report.docx",
            "word/document.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        )
        metadata = validated_upload_metadata(
            upload=valid,
            allowed_extensions={"docx"},
            max_upload_bytes=1024 * 1024,
        )
        self.assertEqual(
            metadata[1],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        disguised_presentation = ooxml_upload(
            "presentation.docx",
            "ppt/presentation.xml",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        )
        with self.assertRaisesMessage(ValidationError, "does not match"):
            validated_upload_metadata(
                upload=disguised_presentation,
                allowed_extensions={"docx"},
                max_upload_bytes=1024 * 1024,
            )

    def test_ambiguous_legacy_office_upload_is_rejected(self):
        legacy = SimpleUploadedFile(
            "legacy.doc",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy",
            content_type="application/msword",
        )
        with self.assertRaisesMessage(ValidationError, "cannot be validated safely"):
            validated_upload_metadata(
                upload=legacy,
                allowed_extensions={"doc"},
                max_upload_bytes=1024,
            )
