import os
import sys

import pymupdf as fitz
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QImage, QPixmap, QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QLabel, QPushButton, QFileDialog, QHBoxLayout,
    QVBoxLayout, QFormLayout, QSpinBox, QLineEdit, QProgressBar, QMessageBox,
    QGroupBox, QSplitter, QToolBar, QListWidget, QListWidgetItem, QInputDialog,
    QAbstractItemView, QComboBox,
)

from .canvas import PdfCanvas
from .constants import PREVIEW_DPI, ASPECT_W, ASPECT_H, TARGET_W, TARGET_H
from .exporter import SequentialExportWorker
from .presets import load_presets, save_presets
from .region_sets import load_region_sets, save_region_sets


def render_page_to_pixmap(page: "fitz.Page", dpi: int) -> QPixmap:
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
    image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 영역 자르기 → PNG 내보내기")
        self.resize(1200, 800)
        base_dir = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(__file__))
        icon_path = os.path.join(base_dir, "resources", "icon.ico")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.doc: fitz.Document | None = None
        self.pdf_path: str | None = None
        self.page_index = 0

        self._updating_fields = False
        self._worker: SequentialExportWorker | None = None
        self.presets: list[dict] = load_presets()
        self.regions: list[dict] = []
        self._active_region_tag: str | None = None
        self.region_sets: list[dict] = load_region_sets()

        self._build_ui()
        self._refresh_preset_list()
        self._refresh_region_list()
        self._refresh_region_set_combo()
        self._update_controls_enabled()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        toolbar = QToolBar()
        self.addToolBar(toolbar)
        open_btn = QPushButton("PDF 열기")
        open_btn.clicked.connect(self.open_pdf)
        toolbar.addWidget(open_btn)
        self.file_label = QLabel("파일 없음")
        toolbar.addWidget(self.file_label)

        self.canvas = PdfCanvas()
        self.canvas.selectionChanged.connect(self._on_canvas_selection_changed)
        self.canvas.presetDragFinished.connect(self._on_preset_drag_finished)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("◀ 이전 페이지")
        self.next_btn = QPushButton("다음 페이지 ▶")
        self.prev_btn.clicked.connect(lambda: self._change_preview_page(-1))
        self.next_btn.clicked.connect(lambda: self._change_preview_page(1))
        self.page_label = QLabel("- / -")
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.page_label)
        nav.addWidget(self.next_btn)
        nav.addStretch(1)

        drag_hint = QLabel(
            "왼쪽 드래그: 영역 선택 / 오른쪽 드래그: 크기를 프리셋으로 저장\n"
            "캔버스 클릭 후 방향키: 1px 이동 (Shift+방향키: 10px 이동)"
        )
        drag_hint.setStyleSheet("color: gray; font-size: 11px;")

        left = QVBoxLayout()
        left.addLayout(nav)
        left.addWidget(self.canvas)
        left.addWidget(drag_hint)
        left_widget = QWidget()
        left_widget.setLayout(left)

        # -- right panel -------------------------------------------------
        coord_group = QGroupBox("자를 영역 (미리보기 픽셀 좌표, 16:9 고정)")
        form = QFormLayout()
        self.x_spin = self._make_spin()
        self.y_spin = self._make_spin()
        self.w_spin = self._make_spin()
        self.h_spin = self._make_spin()
        self.h_spin.setEnabled(False)  # height is derived from width to keep 16:9
        form.addRow("X", self.x_spin)
        form.addRow("Y", self.y_spin)
        form.addRow("너비(W)", self.w_spin)
        form.addRow("높이(H, 자동)", self.h_spin)
        coord_group.setLayout(form)

        for spin in (self.x_spin, self.y_spin, self.w_spin):
            spin.valueChanged.connect(self._on_spin_changed)

        preset_group = QGroupBox("크기 프리셋")
        preset_layout = QVBoxLayout()
        self.preset_list = QListWidget()
        self.preset_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.preset_list.model().rowsMoved.connect(self._on_preset_reordered)
        self.preset_list.itemDoubleClicked.connect(lambda _: self._apply_selected_preset())
        preset_layout.addWidget(self.preset_list)
        preset_btn_row = QHBoxLayout()
        apply_preset_btn = QPushButton("적용")
        apply_preset_btn.clicked.connect(self._apply_selected_preset)
        delete_preset_btn = QPushButton("삭제")
        delete_preset_btn.clicked.connect(self._delete_selected_preset)
        preset_btn_row.addWidget(apply_preset_btn)
        preset_btn_row.addWidget(delete_preset_btn)
        preset_layout.addLayout(preset_btn_row)
        preset_group.setLayout(preset_layout)

        regions_group = QGroupBox("내보낼 영역 목록 (컷 순서)")
        regions_layout = QVBoxLayout()
        self.region_list = QListWidget()
        self.region_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.region_list.model().rowsMoved.connect(self._on_region_reordered)
        self.region_list.itemDoubleClicked.connect(lambda _: self._load_selected_region())
        regions_layout.addWidget(self.region_list)
        region_btn_row1 = QHBoxLayout()
        add_region_btn = QPushButton("+ 현재 영역 추가")
        add_region_btn.clicked.connect(self._add_current_region)
        region_btn_row1.addWidget(add_region_btn)
        regions_layout.addLayout(region_btn_row1)
        region_btn_row2 = QHBoxLayout()
        load_region_btn = QPushButton("불러오기")
        load_region_btn.clicked.connect(self._load_selected_region)
        delete_region_btn = QPushButton("삭제")
        delete_region_btn.clicked.connect(self._delete_selected_region)
        region_btn_row2.addWidget(load_region_btn)
        region_btn_row2.addWidget(delete_region_btn)
        regions_layout.addLayout(region_btn_row2)
        regions_hint = QLabel(
            "목록이 비어 있으면 지금 그려둔 영역 하나만 내보냅니다.\n"
            "1페이지 영역1 → 1페이지 영역2 → 2페이지 영역1 ... 순서로 번호가 매겨집니다.\n"
            "목록에서 항목을 드래그하면 컷 순서를 바꿀 수 있습니다."
        )
        regions_hint.setWordWrap(True)
        regions_hint.setStyleSheet("color: gray; font-size: 11px;")
        regions_layout.addWidget(regions_hint)

        save_set_btn = QPushButton("현재 목록을 세트로 저장...")
        save_set_btn.clicked.connect(self._save_region_set)
        regions_layout.addWidget(save_set_btn)

        set_row = QHBoxLayout()
        self.region_set_combo = QComboBox()
        set_row.addWidget(self.region_set_combo)
        regions_layout.addLayout(set_row)

        set_btn_row = QHBoxLayout()
        load_set_btn = QPushButton("세트 불러오기")
        load_set_btn.clicked.connect(self._load_region_set)
        delete_set_btn = QPushButton("세트 삭제")
        delete_set_btn.clicked.connect(self._delete_region_set)
        set_btn_row.addWidget(load_set_btn)
        set_btn_row.addWidget(delete_set_btn)
        regions_layout.addLayout(set_btn_row)

        set_hint = QLabel("같은 레이아웃(예: 같은 스토리보드 양식)의 다른 PDF에서 영역 조합을 재사용할 때 사용하세요.")
        set_hint.setWordWrap(True)
        set_hint.setStyleSheet("color: gray; font-size: 11px;")
        regions_layout.addWidget(set_hint)

        regions_group.setLayout(regions_layout)

        out_group = QGroupBox("출력")
        out_form = QFormLayout()
        self.out_dir_edit = QLineEdit()
        browse_btn = QPushButton("찾아보기...")
        browse_btn.clicked.connect(self._browse_output_dir)
        out_dir_row = QHBoxLayout()
        out_dir_row.addWidget(self.out_dir_edit)
        out_dir_row.addWidget(browse_btn)
        out_dir_row_widget = QWidget()
        out_dir_row_widget.setLayout(out_dir_row)
        out_form.addRow("저장 폴더", out_dir_row_widget)
        out_hint = QLabel("잘라낸 이미지는 이 폴더에 001, 002, 003... 순서대로 저장됩니다.")
        out_hint.setWordWrap(True)
        out_hint.setStyleSheet("color: gray; font-size: 11px;")
        out_form.addRow("", out_hint)
        out_group.setLayout(out_form)

        self.export_btn = QPushButton(f"내보내기 ({TARGET_W}x{TARGET_H} PNG)")
        self.export_btn.clicked.connect(self._start_export)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.status_label = QLabel("")

        right = QVBoxLayout()
        right.addWidget(coord_group)
        right.addWidget(preset_group)
        right.addWidget(regions_group)
        right.addWidget(out_group)
        right.addWidget(self.export_btn)
        right.addWidget(self.progress_bar)
        right.addWidget(self.status_label)
        right.addStretch(1)
        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setFixedWidth(320)

        splitter = QSplitter()
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)

        self.setCentralWidget(splitter)

    def _make_spin(self) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 100000)
        spin.setSingleStep(1)
        return spin

    # -------------------------------------------------------------- state
    def _update_controls_enabled(self):
        has_doc = self.doc is not None
        self.prev_btn.setEnabled(has_doc)
        self.next_btn.setEnabled(has_doc)
        self.export_btn.setEnabled(has_doc)
        for spin in (self.x_spin, self.y_spin, self.w_spin):
            spin.setEnabled(has_doc)

    # ------------------------------------------------------------- actions
    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "PDF 파일 선택", "", "PDF Files (*.pdf)")
        if not path:
            return
        try:
            doc = fitz.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "PDF 열기 실패", f"PDF를 열 수 없습니다:\n{exc}")
            return
        if doc.page_count == 0:
            QMessageBox.critical(self, "PDF 열기 실패", "페이지가 없는 PDF입니다.")
            return

        self.doc = doc
        self.pdf_path = path
        self.page_index = 0
        self.file_label.setText(f"{os.path.basename(path)} ({doc.page_count} 페이지)")

        default_dir = os.path.join(os.path.dirname(path), f"{os.path.splitext(os.path.basename(path))[0]}_export")
        self.out_dir_edit.setText(default_dir)

        self.regions = []
        self._active_region_tag = None
        self._refresh_region_list()

        self._render_current_page()
        self._set_default_selection()
        self._update_controls_enabled()

    def _render_current_page(self):
        page = self.doc[self.page_index]
        pixmap = render_page_to_pixmap(page, PREVIEW_DPI)
        self.canvas.load_page(pixmap)
        self.page_label.setText(f"{self.page_index + 1} / {self.doc.page_count}")

    def _change_preview_page(self, delta: int):
        if self.doc is None:
            return
        new_index = self.page_index + delta
        if 0 <= new_index < self.doc.page_count:
            self.page_index = new_index
            current_rect = self.canvas.selection_rect()
            self._render_current_page()
            self.canvas.set_selection_rect(current_rect)

    def _set_default_selection(self):
        bounds = self.canvas.bounds
        w = bounds.width() * 0.6
        h = w * ASPECT_H / ASPECT_W
        if h > bounds.height():
            h = bounds.height() * 0.6
            w = h * ASPECT_W / ASPECT_H
        x = (bounds.width() - w) / 2
        y = (bounds.height() - h) / 2
        rect = QRectF(x, y, w, h)
        self.canvas.set_selection_rect(rect)
        self._sync_fields_from_rect(rect)

    def _on_canvas_selection_changed(self, rect: QRectF):
        self._sync_fields_from_rect(rect)

    def _sync_fields_from_rect(self, rect: QRectF):
        self._updating_fields = True
        self.x_spin.setValue(round(rect.x()))
        self.y_spin.setValue(round(rect.y()))
        self.w_spin.setValue(round(rect.width()))
        self.h_spin.setValue(round(rect.height()))
        self._updating_fields = False

    def _on_spin_changed(self):
        if self._updating_fields or self.doc is None:
            return
        self._apply_crop_size(self.w_spin.value(), x=self.x_spin.value(), y=self.y_spin.value())

    def _apply_crop_size(self, width_px: int, x: int | None = None, y: int | None = None):
        """Set the selection to the given width (16:9 derived height), clamped
        inside the current page so the ratio is never broken by page edges."""
        bounds = self.canvas.bounds
        if bounds.isEmpty():
            return
        w = min(max(width_px, 1), bounds.width())
        h = round(w * ASPECT_H / ASPECT_W)
        if h > bounds.height():
            h = bounds.height()
            w = round(h * ASPECT_W / ASPECT_H)

        cur = self.canvas.selection_rect()
        x = cur.x() if x is None else x
        y = cur.y() if y is None else y
        x = min(max(x, 0), bounds.width() - w)
        y = min(max(y, 0), bounds.height() - h)

        rect = QRectF(x, y, w, h)
        self.canvas.set_selection_rect(rect)
        self._sync_fields_from_rect(rect)

    # ------------------------------------------------------------ presets
    def _refresh_preset_list(self):
        self.preset_list.clear()
        for preset in self.presets:
            width_px = round(preset["width_pt"] * PREVIEW_DPI / 72.0)
            height_px = round(width_px * ASPECT_H / ASPECT_W)
            item = QListWidgetItem(f"{preset['name']} ({width_px}x{height_px})")
            item.setData(Qt.ItemDataRole.UserRole, preset)
            self.preset_list.addItem(item)

    def _on_preset_reordered(self, *_args):
        reordered = []
        for row in range(self.preset_list.count()):
            preset = self.preset_list.item(row).data(Qt.ItemDataRole.UserRole)
            reordered.append(preset)
        self.presets = reordered
        save_presets(self.presets)

    def _on_preset_drag_finished(self, rect: QRectF):
        name, ok = QInputDialog.getText(self, "크기 프리셋 저장", "이 드래그 크기를 저장할 이름을 입력하세요:")
        if not ok or not name.strip():
            return
        width_pt = rect.width() * 72.0 / PREVIEW_DPI
        self.presets.append({"name": name.strip(), "width_pt": width_pt})
        save_presets(self.presets)
        self._refresh_preset_list()
        self.preset_list.setCurrentRow(len(self.presets) - 1)

    def _apply_selected_preset(self):
        item = self.preset_list.currentItem()
        if item is None or self.doc is None:
            return
        preset = item.data(Qt.ItemDataRole.UserRole)
        width_px = round(preset["width_pt"] * PREVIEW_DPI / 72.0)
        self._apply_crop_size(width_px)

    def _delete_selected_preset(self):
        item = self.preset_list.currentItem()
        if item is None:
            return
        preset = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "프리셋 삭제", f'"{preset["name"]}" 프리셋을 삭제할까요?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.presets.remove(preset)
        save_presets(self.presets)
        self._refresh_preset_list()

    # ------------------------------------------------------------ regions
    def _refresh_region_list(self):
        self.region_list.clear()
        for order, region in enumerate(self.regions, start=1):
            rect = region["rect"]
            item = QListWidgetItem(
                f"{order}. {region['tag']} "
                f"({round(rect.width())}x{round(rect.height())} @ {round(rect.x())},{round(rect.y())})"
            )
            item.setData(Qt.ItemDataRole.UserRole, region)
            self.region_list.addItem(item)
        self.canvas.set_reference_regions([(r["tag"], r["rect"]) for r in self.regions])
        self._update_export_button_text()

    def _update_export_button_text(self):
        region_count = max(len(self.regions), 1)
        page_count = self.doc.page_count if self.doc is not None else 0
        if page_count:
            total = page_count * region_count
            self.export_btn.setText(f"내보내기 ({total}장, {TARGET_W}x{TARGET_H} PNG)")
        else:
            self.export_btn.setText(f"내보내기 ({TARGET_W}x{TARGET_H} PNG)")

    def _on_region_reordered(self, *_args):
        self.regions = [
            self.region_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.region_list.count())
        ]
        # Rebuilding the list re-numbers the rows, but it must not happen
        # while the view is still finishing the drop that triggered this.
        QTimer.singleShot(0, self._refresh_region_list)

    def _suggest_region_tag(self) -> str:
        return self._active_region_tag or f"cut{len(self.regions) + 1}"

    def _add_current_region(self):
        if self.doc is None:
            return
        rect = self.canvas.selection_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            QMessageBox.warning(self, "영역 없음", "먼저 캔버스에서 잘라낼 영역을 지정해주세요.")
            return
        name, ok = QInputDialog.getText(self, "영역 이름", "이 영역의 이름(태그)을 입력하세요:", text=self._suggest_region_tag())
        if not ok or not name.strip():
            return
        tag = name.strip()

        existing = next((r for r in self.regions if r["tag"] == tag), None)
        if existing is not None:
            existing["rect"] = QRectF(rect)
        else:
            self.regions.append({"tag": tag, "rect": QRectF(rect)})
        self._active_region_tag = tag
        self._refresh_region_list()

    def _load_selected_region(self):
        item = self.region_list.currentItem()
        if item is None or self.doc is None:
            return
        region = item.data(Qt.ItemDataRole.UserRole)
        self._active_region_tag = region["tag"]
        self.canvas.set_selection_rect(QRectF(region["rect"]))
        self._sync_fields_from_rect(region["rect"])

    def _delete_selected_region(self):
        item = self.region_list.currentItem()
        if item is None:
            return
        region = item.data(Qt.ItemDataRole.UserRole)
        self.regions.remove(region)
        if self._active_region_tag == region["tag"]:
            self._active_region_tag = None
        self._refresh_region_list()

    # -------------------------------------------------------- region sets
    def _refresh_region_set_combo(self):
        current = self.region_set_combo.currentText() if self.region_set_combo.count() else ""
        self.region_set_combo.clear()
        self.region_set_combo.addItems([s["name"] for s in self.region_sets])
        idx = self.region_set_combo.findText(current)
        if idx >= 0:
            self.region_set_combo.setCurrentIndex(idx)

    def _save_region_set(self):
        if not self.regions:
            QMessageBox.warning(self, "영역 없음", "저장할 영역이 없습니다. 먼저 '+ 현재 영역 추가'로 영역을 추가해주세요.")
            return
        name, ok = QInputDialog.getText(self, "영역 세트 저장", "이 영역 조합을 저장할 이름을 입력하세요:")
        if not ok or not name.strip():
            return
        name = name.strip()

        px_to_pt = 72.0 / PREVIEW_DPI
        regions_pt = [
            {
                "tag": r["tag"],
                "x_pt": r["rect"].x() * px_to_pt,
                "y_pt": r["rect"].y() * px_to_pt,
                "width_pt": r["rect"].width() * px_to_pt,
                "height_pt": r["rect"].height() * px_to_pt,
            }
            for r in self.regions
        ]

        existing = next((s for s in self.region_sets if s["name"] == name), None)
        if existing is not None:
            existing["regions"] = regions_pt
        else:
            self.region_sets.append({"name": name, "regions": regions_pt})
        save_region_sets(self.region_sets)
        self._refresh_region_set_combo()
        self.region_set_combo.setCurrentText(name)

    def _load_region_set(self):
        if self.doc is None:
            return
        name = self.region_set_combo.currentText()
        if not name:
            return
        region_set = next((s for s in self.region_sets if s["name"] == name), None)
        if region_set is None:
            return

        if self.regions:
            reply = QMessageBox.question(
                self, "영역 목록 교체",
                f'현재 영역 목록을 "{name}" 세트 내용으로 교체할까요?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        bounds = self.canvas.bounds
        pt_to_px = PREVIEW_DPI / 72.0
        new_regions = []
        for entry in region_set["regions"]:
            w = min(entry["width_pt"] * pt_to_px, bounds.width())
            h = round(w * ASPECT_H / ASPECT_W)
            if h > bounds.height():
                h = bounds.height()
                w = round(h * ASPECT_W / ASPECT_H)
            x = min(max(entry["x_pt"] * pt_to_px, 0), bounds.width() - w)
            y = min(max(entry["y_pt"] * pt_to_px, 0), bounds.height() - h)
            new_regions.append({"tag": entry["tag"], "rect": QRectF(x, y, w, h)})

        self.regions = new_regions
        self._active_region_tag = None
        self._refresh_region_list()

    def _delete_region_set(self):
        name = self.region_set_combo.currentText()
        if not name:
            return
        region_set = next((s for s in self.region_sets if s["name"] == name), None)
        if region_set is None:
            return
        reply = QMessageBox.question(
            self, "세트 삭제", f'"{name}" 세트를 삭제할까요?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.region_sets.remove(region_set)
        save_region_sets(self.region_sets)
        self._refresh_region_set_combo()

    def _browse_output_dir(self):
        current = self.out_dir_edit.text() or os.getcwd()
        path = QFileDialog.getExistingDirectory(self, "저장 폴더 선택", current)
        if path:
            self.out_dir_edit.setText(path)

    def _collect_export_regions(self) -> list[QRectF] | None:
        """The region list defines the cut order; with an empty list the
        currently drawn selection is exported on its own."""
        if self.regions:
            return [region["rect"] for region in self.regions]

        rect = self.canvas.selection_rect()
        if rect.width() <= 0 or rect.height() <= 0:
            QMessageBox.warning(self, "영역 없음", "먼저 잘라낼 영역을 지정해주세요.")
            return None
        return [rect]

    def _start_export(self):
        if self.doc is None or self.pdf_path is None:
            return
        output_dir = self.out_dir_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, "저장 폴더 없음", "저장 폴더를 지정해주세요.")
            return

        regions = self._collect_export_regions()
        if regions is None:
            return

        if os.path.isdir(output_dir) and os.listdir(output_dir):
            reply = QMessageBox.question(
                self, "덮어쓰기 확인",
                f"저장 폴더에 이미 파일이 있습니다. 덮어쓸까요?\n{output_dir}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        base_name = os.path.splitext(os.path.basename(self.pdf_path))[0]

        self.export_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(self.doc.page_count * len(regions))
        self.status_label.setText("내보내는 중...")

        self._worker = SequentialExportWorker(self.pdf_path, regions, output_dir, base_name)
        self._worker.progress.connect(self._on_export_progress)
        self._worker.finished_ok.connect(self._on_export_finished)
        self._worker.failed.connect(self._on_export_failed)
        self._worker.start()

    def _on_export_progress(self, done: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(done)
        self.status_label.setText(f"{done}/{total} 장 저장 중")

    def _on_export_finished(self, output_dir: str, count: int):
        self.status_label.setText(f"완료: {count}장 저장됨 (001 ~ {str(count).zfill(3)})")
        self.export_btn.setEnabled(True)
        QMessageBox.information(
            self, "내보내기 완료",
            f"{count}장의 PNG를 순서대로 저장했습니다:\n{output_dir}",
        )

    def _on_export_failed(self, message: str):
        self.status_label.setText("실패")
        self.export_btn.setEnabled(True)
        QMessageBox.critical(self, "내보내기 실패", message)
