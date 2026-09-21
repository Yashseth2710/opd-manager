"""Telling a file's real type from its first bytes, and tidying its name."""

from __future__ import annotations

import pytest

from app.services.file_checks import (
    HEIC,
    JPEG,
    PDF,
    PNG,
    WEBP,
    clean_name,
    extension_of,
    sniff,
    title_from,
)


@pytest.mark.parametrize(
    ("head", "kind"),
    [
        (b"%PDF-1.4\n", PDF),
        (b"\xef\xbb\xbf\r\n%PDF-1.7", PDF),
        (b"\x00" * 500 + b"%PDF-1.3", PDF),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", JPEG),
        (b"\xff\xd8\xff\xe1\x00\x00Exif", JPEG),
        (b"\x89PNG\r\n\x1a\n\x00\x00", PNG),
        (b"RIFF\x00\x00\x00\x00WEBPVP8L", WEBP),
        (b"\x00\x00\x00\x18ftypheic", HEIC),
        (b"\x00\x00\x00\x1cftypmif1", HEIC),
    ],
)
def test_the_kinds_it_knows(head: bytes, kind: str) -> None:
    assert sniff(head) == kind


@pytest.mark.parametrize(
    "head",
    [
        b"",
        b"%PD",
        b"\x00" * 1100 + b"%PDF-1.3",
        b"<html>",
        b"<?xml version='1.0'?><svg",
        b"GIF89a",
        b"RIFF\x00\x00\x00\x00WAVEfmt ",
        b"\x00\x00\x00\x18ftypmp42",
        b"\x89PNG",
        b"MZ\x90\x00",
        b"PK\x03\x04",
    ],
)
def test_anything_else_is_nothing_it_knows(head: bytes) -> None:
    assert sniff(head) is None


@pytest.mark.parametrize(
    ("name", "extension"),
    [
        ("report.PDF", "pdf"),
        ("a.b.jpeg", "jpeg"),
        ("no extension", None),
        (".hidden", None),
        ("trailing.", None),
    ],
)
def test_extensions(name: str, extension: str | None) -> None:
    assert extension_of(name) == extension


@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        ("C:\\fakepath\\report.pdf", "report.pdf"),
        ("/home/user/scans/xray.png", "xray.png"),
        ("../../etc/passwd", "passwd"),
        ("bad\x00name\r\n.pdf", "badname.pdf"),
        ("  spaced    out .pdf ", "spaced out .pdf"),
        ("", "file"),
        ("\x01\x02", "file"),
        ("a" * 300 + ".pdf", "a" * 200),
    ],
)
def test_names_are_tidied(sent: str, kept: str) -> None:
    assert clean_name(sent) == kept


@pytest.mark.parametrize(
    ("name", "title"),
    [
        ("CBC_report-21.09.pdf", "CBC report-21.09"),
        ("IMG_20240912_101500.jpg", "IMG 20240912 101500"),
        ("WhatsApp Image", "WhatsApp Image"),
        ("___.pdf", "Untitled"),
        ("x" * 200 + ".pdf", "x" * 120),
    ],
)
def test_titles_from_names(name: str, title: str) -> None:
    assert title_from(name) == title
