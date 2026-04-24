from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


BlockType = Literal["text", "image", "unknown"]
PdfKind = Literal["born_digital", "scanned", "hybrid"]


class BoundingBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class PlaceholderMap(BaseModel):
    key: str
    value: str
    kind: str


class TextSpan(BaseModel):
    text: str = ""
    font: Optional[str] = None
    size: Optional[float] = None
    flags: Optional[int] = None
    color: Optional[int] = None
    bbox: BoundingBox


class TextLine(BaseModel):
    bbox: BoundingBox
    spans: list[TextSpan] = Field(default_factory=list)
    text: str = ""
    protected_text: str = ""
    placeholders: list[PlaceholderMap] = Field(default_factory=list)
    translation_candidate: bool = True
    translated_text: str = ""
    restored_text: str = ""


class TextBlock(BaseModel):
    page_number: int
    block_index: int
    block_type: BlockType = "text"
    bbox: BoundingBox
    text: str = ""
    translate: bool = True
    role: str = "content"
    repeat_count: int = 1
    lines: list[TextLine] = Field(default_factory=list)


class OcrCandidate(BaseModel):
    page_number: int
    candidate_index: int
    source_block_type: BlockType = "image"
    bbox: BoundingBox
    width: float
    height: float
    area_ratio: float = 0.0
    reason: str = "image_block"


class PageModel(BaseModel):
    page_number: int
    width: float
    height: float
    text_blocks: list[TextBlock] = Field(default_factory=list)
    ocr_candidates: list[OcrCandidate] = Field(default_factory=list)
    image_count: int = 0
    raw_text: str = ""
    block_count: int = 0


class DocumentModel(BaseModel):
    source_path: str
    pdf_kind: PdfKind
    page_count: int
    pages: list[PageModel] = Field(default_factory=list)
