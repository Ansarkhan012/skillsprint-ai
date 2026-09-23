"""Deterministic, source-aware PDF/DOCX extraction. No LLM or OCR dependency."""

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from io import BytesIO
import re
from statistics import median
from uuid import UUID
from zipfile import BadZipFile, ZipFile

import fitz
from docx import Document as DocxDocument
from docx.document import Document as DocxType
from docx.table import Table
from docx.text.paragraph import Paragraph
from pydantic import BaseModel, ConfigDict, Field, model_validator


PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PARSER_VERSION = "phase2-1"


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID | None = None
    document_code: str = Field(pattern=r"^[A-Z0-9_-]{2,64}$")
    title: str = Field(min_length=1, max_length=240)
    category: str = Field(min_length=1, max_length=100)
    department_id: UUID | None = None
    version_label: str = Field(min_length=1, max_length=64)
    effective_date: date
    expiry_date: date | None = None

    @model_validator(mode="after")
    def valid_dates(self) -> "DocumentInput":
        if self.expiry_date and self.expiry_date < self.effective_date:
            raise ValueError("expiry_date must not precede effective_date")
        for value in (self.title, self.category, self.version_label):
            if not value.strip():
                raise ValueError("document metadata must not be blank")
        return self


class DocumentProblem(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class SourceUnit:
    text: str
    source_location: dict
    heading: str | None = None
    section_path: str | None = None
    page_number: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()


def validate_file(filename: str | None, content_type: str | None, data: bytes, max_bytes: int) -> tuple[str, str]:
    if not data:
        raise DocumentProblem("EMPTY_FILE")
    if len(data) > max_bytes:
        raise DocumentProblem("FILE_TOO_LARGE", 413)
    if not filename or len(filename) > 240 or any(ch in filename for ch in "/\\\x00\r\n") or filename in (".", ".."):
        raise DocumentProblem("UNSAFE_FILENAME")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    expected = {"pdf": PDF_MIME, "docx": DOCX_MIME}.get(suffix)
    if expected is None:
        raise DocumentProblem("UNSUPPORTED_FILE_TYPE", 415)
    if content_type and content_type.split(";", 1)[0].strip().lower() not in (expected, "application/octet-stream"):
        raise DocumentProblem("MIME_MISMATCH", 415)
    if suffix == "pdf":
        if not data.startswith(b"%PDF-"):
            raise DocumentProblem("MIME_MISMATCH", 415)
    else:
        try:
            with ZipFile(BytesIO(data)) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise DocumentProblem("MIME_MISMATCH", 415)
                if any(name.lower().endswith("vbaproject.bin") for name in names):
                    raise DocumentProblem("UNSUPPORTED_FILE_TYPE", 415)
                infos = archive.infolist()
                if len(infos) > 2000 or sum(item.file_size for item in infos) > 100 * 1024 * 1024:
                    raise DocumentProblem("UNSAFE_DOCX_ARCHIVE", 422)
                if any(item.file_size > max(item.compress_size, 1) * 200 for item in infos):
                    raise DocumentProblem("UNSAFE_DOCX_ARCHIVE", 422)
        except BadZipFile as exc:
            raise DocumentProblem("MIME_MISMATCH", 415) from exc
    return expected, sha256(data).hexdigest()


def parse_pdf(data: bytes) -> list[SourceUnit]:
    try:
        document = fitz.open(stream=data, filetype="pdf")
        if document.is_encrypted:
            raise DocumentProblem("PDF_ENCRYPTED_NEEDS_REVIEW")
        units: list[SourceUnit] = []
        for page_index, page in enumerate(document):
            raw = page.get_text("dict", sort=True)
            blocks = []
            sizes = []
            for source_block_index, block in enumerate(raw.get("blocks", []), 1):
                lines = block.get("lines", [])
                spans = [span for line in lines for span in line.get("spans", [])]
                content = normalize(" ".join(span.get("text", "") for span in spans))
                if content:
                    size = max((float(span.get("size", 0)) for span in spans), default=0)
                    sizes.extend(float(span.get("size", 0)) for span in spans if span.get("text", "").strip())
                    blocks.append((content, size, block.get("bbox"), source_block_index))
            baseline = median(sizes) if sizes else 0
            heading: str | None = None
            for content, size, bbox, source_block_index in blocks:
                locator = {"kind": "pdf", "page": page_index + 1,
                           "block": source_block_index, "bbox": bbox}
                if baseline and size >= baseline * 1.25 and len(content) <= 140:
                    heading = content
                    units.append(SourceUnit(text=content, heading=heading, section_path=heading,
                                            page_number=page_index + 1,
                                            source_location={**locator, "kind_detail": "heading"}))
                    continue
                units.append(SourceUnit(
                    text=content, heading=heading, section_path=heading,
                    page_number=page_index + 1,
                    source_location=locator,
                ))
        document.close()
        return units
    except DocumentProblem:
        raise
    except Exception as exc:
        raise DocumentProblem("PDF_PARSE_FAILED") from exc


def parse_docx(data: bytes) -> list[SourceUnit]:
    try:
        document: DocxType = DocxDocument(BytesIO(data))
        units: list[SourceUnit] = []
        section: list[str] = []
        paragraph_index = 0
        table_index = 0
        for child in document.element.body.iterchildren():
            if child.tag.endswith("}p"):
                paragraph_index += 1
                paragraph = Paragraph(child, document)
                content = normalize(paragraph.text)
                if not content:
                    continue
                style = paragraph.style.name if paragraph.style is not None else ""
                if style.lower().startswith("heading") or style.lower() == "title":
                    match = re.search(r"(\d+)$", style)
                    level = int(match.group(1)) if match else 1
                    level = max(1, min(level, 9))
                    section = section[:level - 1] + [content]
                    units.append(SourceUnit(
                        text=content, heading=content, section_path=" / ".join(section),
                        paragraph_start=paragraph_index, paragraph_end=paragraph_index,
                        source_location={"kind": "docx", "paragraph": paragraph_index,
                                         "style": style, "kind_detail": "heading"},
                    ))
                    continue
                units.append(SourceUnit(
                    text=content, heading=section[-1] if section else None,
                    section_path=" / ".join(section) if section else None,
                    paragraph_start=paragraph_index, paragraph_end=paragraph_index,
                    source_location={"kind": "docx", "paragraph": paragraph_index, "style": style},
                ))
            elif child.tag.endswith("}tbl"):
                table_index += 1
                table = Table(child, document)
                for row_index, row in enumerate(table.rows, 1):
                    for cell_index, cell in enumerate(row.cells, 1):
                        content = normalize(cell.text)
                        if content:
                            units.append(SourceUnit(
                                text=content, heading=section[-1] if section else None,
                                section_path=" / ".join(section) if section else None,
                                source_location={"kind": "docx", "table": table_index,
                                    "row": row_index, "cell": cell_index},
                            ))
        return units
    except Exception as exc:
        raise DocumentProblem("DOCX_PARSE_FAILED") from exc


def chunk_units(units: list[SourceUnit], version_id: UUID, max_chars: int, overlap: int) -> list[dict]:
    chunks: list[dict] = []
    for unit in units:
        content = normalize(unit.text)
        if not content:
            continue
        start = 0
        while start < len(content):
            end = min(start + max_chars, len(content))
            if end < len(content):
                split = content.rfind(" ", start + max_chars // 2, end)
                if split > start:
                    end = split
            part = content[start:end].strip()
            if part:
                sequence = len(chunks)
                locator = {**unit.source_location, "char_start": start, "char_end": end}
                text_hash = sha256(part.encode("utf-8")).hexdigest()
                stable = f"{version_id}|{sequence}|{locator}|{text_hash}"
                chunks.append({
                    "chunk_key": sha256(stable.encode("utf-8")).hexdigest(),
                    "sequence": sequence, "content": part, "text_hash": text_hash,
                    "heading": unit.heading, "section_path": unit.section_path,
                    "source_location": locator, "page_number": unit.page_number,
                    "paragraph_start": unit.paragraph_start, "paragraph_end": unit.paragraph_end,
                    "char_start": start, "char_end": end,
                })
            if end >= len(content):
                break
            start = max(start + 1, end - overlap)
    return chunks
