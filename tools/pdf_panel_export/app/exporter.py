import os

import pymupdf as fitz
from PIL import Image
from PySide6.QtCore import QThread, Signal, QRectF

from .constants import PREVIEW_DPI, TARGET_W, TARGET_H
from .util import sanitize_folder_name


def export_region(doc: "fitz.Document", rect_px: QRectF, output_dir: str, base_name: str,
                   progress_cb=None, is_cancelled=None) -> int:
    """Crop the same page-relative region out of every page of `doc` and
    save each as a TARGET_W x TARGET_H PNG in `output_dir`. Returns the
    number of pages exported."""
    px_to_pt = 72.0 / PREVIEW_DPI
    x0 = rect_px.x() * px_to_pt
    y0 = rect_px.y() * px_to_pt
    w_pt = rect_px.width() * px_to_pt
    h_pt = rect_px.height() * px_to_pt

    if w_pt <= 0 or h_pt <= 0:
        raise ValueError("잘라낼 영역이 지정되지 않았습니다.")

    zoom = TARGET_W / w_pt
    os.makedirs(output_dir, exist_ok=True)

    total = doc.page_count
    digits = max(3, len(str(total)))
    clip = fitz.Rect(x0, y0, x0 + w_pt, y0 + h_pt)
    matrix = fitz.Matrix(zoom, zoom)

    exported = 0
    for i in range(total):
        if is_cancelled and is_cancelled():
            break
        page = doc[i]
        inter = clip & page.rect
        canvas = Image.new("RGB", (TARGET_W, TARGET_H), "white")

        if not inter.is_empty:
            pix = page.get_pixmap(matrix=matrix, clip=inter, colorspace=fitz.csRGB, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            off_x = round((inter.x0 - x0) * zoom)
            off_y = round((inter.y0 - y0) * zoom)
            off_x = min(max(off_x, 0), TARGET_W)
            off_y = min(max(off_y, 0), TARGET_H)

            if off_x + img.width > TARGET_W or off_y + img.height > TARGET_H:
                img = img.crop((0, 0, min(img.width, TARGET_W - off_x), min(img.height, TARGET_H - off_y)))

            canvas.paste(img, (off_x, off_y))

        filename = f"{base_name}_page_{str(i + 1).zfill(digits)}.png"
        canvas.save(os.path.join(output_dir, filename), "PNG")
        exported += 1
        if progress_cb:
            progress_cb(exported, total)

    return exported


class ExportWorker(QThread):
    """Exports a single crop region across every page of the PDF."""

    progress = Signal(int, int)  # (current_page, total_pages)
    finished_ok = Signal(str, int)  # (output_dir, exported_count)
    failed = Signal(str)

    def __init__(self, pdf_path: str, rect_px: QRectF, output_dir: str, base_name: str, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._rect_px = QRectF(rect_px)
        self._output_dir = output_dir
        self._base_name = base_name
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self._export()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _export(self):
        doc = fitz.open(self._pdf_path)
        try:
            exported = export_region(
                doc, self._rect_px, self._output_dir, self._base_name,
                progress_cb=lambda c, t: self.progress.emit(c, t),
                is_cancelled=lambda: self._cancelled,
            )
        finally:
            doc.close()

        if self._cancelled:
            self.failed.emit("내보내기가 취소되었습니다.")
        else:
            self.finished_ok.emit(self._output_dir, exported)


class MultiRegionExportWorker(QThread):
    """Exports several named crop regions, each across every page of the
    PDF, into their own sub-folder under `output_dir`."""

    progress = Signal(int, int, str)  # (done_units, total_units, current_region_tag)
    finished_ok = Signal(str, int, int)  # (output_dir, region_count, total_files)
    failed = Signal(str)

    def __init__(self, pdf_path: str, regions: list[tuple[str, QRectF]], output_dir: str,
                 base_name: str, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._regions = [(tag, QRectF(rect)) for tag, rect in regions]
        self._output_dir = output_dir
        self._base_name = base_name
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self._export()
        except Exception as exc:
            self.failed.emit(str(exc))

    def _export(self):
        doc = fitz.open(self._pdf_path)
        try:
            page_count = doc.page_count
            total_units = page_count * len(self._regions)
            done = 0
            total_files = 0

            for tag, rect in self._regions:
                if self._cancelled:
                    break
                region_dir = os.path.join(self._output_dir, sanitize_folder_name(tag))

                def on_progress(current, _total, _tag=tag, _base=done):
                    self.progress.emit(_base + current, total_units, _tag)

                count = export_region(
                    doc, rect, region_dir, self._base_name,
                    progress_cb=on_progress,
                    is_cancelled=lambda: self._cancelled,
                )
                done += page_count
                total_files += count
        finally:
            doc.close()

        if self._cancelled:
            self.failed.emit("내보내기가 취소되었습니다.")
        else:
            self.finished_ok.emit(self._output_dir, len(self._regions), total_files)
