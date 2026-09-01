import os
from typing import Callable

import pymupdf as fitz
from PIL import Image
from PySide6.QtCore import QThread, Signal, QRectF

from .constants import PREVIEW_DPI, TARGET_W, TARGET_H


def crop_page_region(page: "fitz.Page", rect_px: QRectF) -> Image.Image:
    """Render one preview-pixel region of a single page as a
    TARGET_W x TARGET_H image. Parts of the region that fall outside the
    page are left white."""
    px_to_pt = 72.0 / PREVIEW_DPI
    x0 = rect_px.x() * px_to_pt
    y0 = rect_px.y() * px_to_pt
    w_pt = rect_px.width() * px_to_pt
    h_pt = rect_px.height() * px_to_pt

    if w_pt <= 0 or h_pt <= 0:
        raise ValueError("잘라낼 영역이 지정되지 않았습니다.")

    zoom = TARGET_W / w_pt
    clip = fitz.Rect(x0, y0, x0 + w_pt, y0 + h_pt)
    canvas = Image.new("RGB", (TARGET_W, TARGET_H), "white")

    inter = clip & page.rect
    if inter.is_empty:
        return canvas

    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=inter, colorspace=fitz.csRGB, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    off_x = min(max(round((inter.x0 - x0) * zoom), 0), TARGET_W)
    off_y = min(max(round((inter.y0 - y0) * zoom), 0), TARGET_H)
    if off_x + img.width > TARGET_W or off_y + img.height > TARGET_H:
        img = img.crop((0, 0, min(img.width, TARGET_W - off_x), min(img.height, TARGET_H - off_y)))

    canvas.paste(img, (off_x, off_y))
    return canvas


def export_sequential(doc: "fitz.Document", regions: list[QRectF], output_dir: str, base_name: str,
                      progress_cb: Callable[[int, int], None] | None = None,
                      is_cancelled: Callable[[], bool] | None = None) -> int:
    """Crop every region out of every page and save the results as PNGs
    numbered sequentially in reading order: page 1 region 1, page 1
    region 2, ..., page 2 region 1, ... Returns the number of files saved."""
    if not regions:
        raise ValueError("잘라낼 영역이 지정되지 않았습니다.")

    os.makedirs(output_dir, exist_ok=True)

    total = doc.page_count * len(regions)
    digits = max(3, len(str(total)))
    saved = 0

    for page_index in range(doc.page_count):
        page = doc[page_index]
        for rect in regions:
            if is_cancelled and is_cancelled():
                return saved
            image = crop_page_region(page, rect)
            saved += 1
            filename = f"{base_name}_{str(saved).zfill(digits)}.png"
            image.save(os.path.join(output_dir, filename), "PNG")
            if progress_cb:
                progress_cb(saved, total)

    return saved


class SequentialExportWorker(QThread):
    """Exports every region across every page as one sequentially
    numbered PNG series."""

    progress = Signal(int, int)  # (saved_count, total_count)
    finished_ok = Signal(str, int)  # (output_dir, saved_count)
    failed = Signal(str)

    def __init__(self, pdf_path: str, regions: list[QRectF], output_dir: str, base_name: str, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._regions = [QRectF(rect) for rect in regions]
        self._output_dir = output_dir
        self._base_name = base_name
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            self._export()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _export(self) -> None:
        doc = fitz.open(self._pdf_path)
        try:
            saved = export_sequential(
                doc, self._regions, self._output_dir, self._base_name,
                progress_cb=lambda done, total: self.progress.emit(done, total),
                is_cancelled=lambda: self._cancelled,
            )
        finally:
            doc.close()

        if self._cancelled:
            self.failed.emit("내보내기가 취소되었습니다.")
        else:
            self.finished_ok.emit(self._output_dir, saved)
