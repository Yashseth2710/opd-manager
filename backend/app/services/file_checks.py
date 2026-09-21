"""What an uploaded file really is, decided from its first bytes.

The name a file arrives with and the type the browser claims for it are both
whatever the sender says. The bytes at the start of the file are what a PDF
reader or an image decoder will actually act on, so those decide.
"""

from __future__ import annotations

import re
import unicodedata

PDF = "application/pdf"
JPEG = "image/jpeg"
PNG = "image/png"
WEBP = "image/webp"
KINDS = (PDF, JPEG, PNG, WEBP)
EXTENSION = {PDF: "pdf", JPEG: "jpg", PNG: "png", WEBP: "webp"}

# Names a clinic's files come with. Anything else with an extension at all
# is refused before its contents are looked at.
ALLOWED_EXTENSIONS = frozenset({"pdf", "jpg", "jpeg", "jfif", "png", "webp", "heic", "heif"})

# Returned for an iPhone photo that was not converted on the way out. It is
# a real image, but no browser but Safari can show it, so the clinic would
# have a file nobody at the desk can open.
HEIC = "image/heic"

_HEIC_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")


def sniff(head: bytes) -> str | None:
    """The type the bytes say, from the first kilobyte or so of the file."""
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    if head[4:8] == b"ftyp" and head[8:12] in _HEIC_BRANDS:
        return HEIC
    # Readers accept a PDF whose header sits a little way in, after whatever
    # a scanner or a mail gateway put in front of it.
    if b"%PDF-" in head[:1024]:
        return PDF
    return None


def extension_of(name: str) -> str | None:
    stem, dot, extension = name.rpartition(".")
    if not dot or not stem or not extension:
        return None
    return extension.lower()


_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SPACES = re.compile(r"\s+")


def clean_name(name: str) -> str:
    """The name as sent, kept to show and to download with. Anything before a
    slash is a path on the sender's machine, and control characters would
    break the header it is sent back in."""
    name = unicodedata.normalize("NFC", name)
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _SPACES.sub(" ", _CONTROL.sub("", name)).strip()
    return name[:200] or "file"


def title_from(name: str) -> str:
    """A name to show when none was given: CBC_report-21.09.pdf reads as
    CBC report-21.09."""
    stem = name.rsplit(".", 1)[0] if extension_of(name) else name
    title = _SPACES.sub(" ", stem.replace("_", " ")).strip()
    return title[:120] or "Untitled"
