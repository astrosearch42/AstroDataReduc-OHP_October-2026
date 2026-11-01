"""Application Qt6 pour le pipeline de réduction FITS de l'OHP."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import redirect_stdout

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .align_images import align_images, align_images_basic
from .combine_colors import align_channels, combine_channels, detect_channel_candidates
from .make_masters import make_master_dark, make_master_flat, make_master_offset
from .reduce_fits import reduce_images
from .stack_images import stack_images
from .Utils.Utils import (
    DATADIR_GUI,
    Path,
    debayer_bilinear,
    existing_master_files_by_type,
    fits,
    fits_path,
    iter_fits_files,
    np,
    sys,
    version_app,
    write_fits_image,
)


class PipelineWorker(QObject):
    progress = Signal(int)
    message = Signal(str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], object]) -> None:
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self) -> None:
        try:
            with redirect_stdout(WorkerOutput(self.message)):
                result = self.operation()
        except Exception as exc:  # noqa: BLE001 - report worker failures to the GUI
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(result)


class WorkerOutput:
    def __init__(self, signal: object) -> None:
        self.signal = signal
        self.buffer = ""

    def write(self, text: str) -> int:
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line:
                self.signal.emit(line)
        return len(text)

    def flush(self) -> None:
        if self.buffer:
            self.signal.emit(self.buffer)
            self.buffer = ""


class ChannelSelectionDialog(QDialog):
    def __init__(
        self,
        candidates: dict[str, list[tuple[Path, str, fits.Header]]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choisir les fichiers des canaux")
        self.setMinimumWidth(620)
        self.selected_files: dict[str, Path] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Plusieurs fichiers correspondent à certains canaux. "
            "Sélectionnez un fichier pour chaque canal."
        ))
        self._groups: dict[str, list[QRadioButton]] = {}
        for channel, values in candidates.items():
            if len(values) < 2:
                continue
            group = QGroupBox(f"Canal {channel}")
            group.setStyleSheet(
                "QGroupBox { border: 1px solid palette(mid); "
                "border-radius: 4px; margin-top: 8px; padding-top: 8px; }"
            )
            group_layout = QVBoxLayout(group)
            choices_layout = QGridLayout()
            radios: list[QRadioButton] = []
            radio_group = QButtonGroup(group)
            radio_group.setExclusive(True)
            differences = self._header_differences(values)
            tiles: list[QFrame] = []
            for path, _, _ in values:
                file_frame = QFrame()
                file_frame.setFrameShape(QFrame.Shape.StyledPanel)
                file_frame.setStyleSheet(
                    "QFrame { border: 1px solid palette(mid); "
                    "border-radius: 3px; padding: 4px; }"
                )
                file_layout = QVBoxLayout(file_frame)
                radio = QRadioButton(path.name)
                radio_group.addButton(radio)
                radio.setProperty("selected_path", str(path))
                radio.toggled.connect(self._update_accept_button)
                details = QLabel(differences.get(path, "Aucune différence de header."))
                details.setWordWrap(True)
                file_layout.addWidget(radio)
                file_layout.addWidget(details)
                radios.append(radio)
                tiles.append(file_frame)
            for index, tile in enumerate(tiles):
                row, column = divmod(index, 2)
                if index == len(tiles) - 1 and len(tiles) % 2:
                    choices_layout.addWidget(
                        tile, row, 0, 1, 2, Qt.AlignmentFlag.AlignHCenter
                    )
                else:
                    choices_layout.addWidget(tile, row, column)
            group_layout.addLayout(choices_layout)
            self._groups[channel] = radios
            layout.addWidget(group)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._accept_selection)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._update_accept_button()

    @staticmethod
    def _header_differences(
        values: list[tuple[Path, str, fits.Header]],
    ) -> dict[Path, str]:
        keys = sorted({key for _, _, header in values for key in header})
        differing_keys = [
            key for key in keys
            if len({str(header.get(key, "")) for _, _, header in values}) > 1
        ]
        return {
            path: "\n".join(
                f"{key} = {header.get(key, '<absent>')}"
                for key in differing_keys
            )
            for path, _, header in values
        }

    def _update_accept_button(self) -> None:
        enabled = all(
            any(radio.isChecked() for radio in radios)
            for radios in self._groups.values()
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(enabled)

    def _accept_selection(self) -> None:
        self.selected_files = {
            channel: Path(str(radio.property("selected_path")))
            for channel, radios in self._groups.items()
            for radio in radios
            if radio.isChecked()
        }
        self.accept()


class ImageScrollArea(QScrollArea):
    zoom_requested = Signal(int)

    def wheelEvent(self, event: object) -> None:
        angle_delta = event.angleDelta().y()
        if angle_delta:
            self.zoom_requested.emit(1 if angle_delta > 0 else -1)
            event.accept()
        else:
            super().wheelEvent(event)


class FitsViewer(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.file_label = QLabel("Aucun fichier FITS chargé")
        self.file_label.setWordWrap(True)
        self.display_notice = QLabel()
        self.display_notice.setWordWrap(True)
        self.image = QLabel("Sélectionnez un fichier FITS à afficher.")
        self.source_pixmap: QPixmap | None = None
        self.zoom_factor = 1.0
        self.data: np.ndarray | None = None
        self.header: fits.Header | None = None
        self.source_path: Path | None = None
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(320, 240)
        self.image.setScaledContents(False)
        self.image_scroll = ImageScrollArea()
        self.image_scroll.setWidget(self.image)
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_scroll.zoom_requested.connect(self.change_zoom)
        zoom_out = QPushButton("−")
        zoom_out.clicked.connect(lambda: self.change_zoom(-1))
        zoom_in = QPushButton("+")
        zoom_in.clicked.connect(lambda: self.change_zoom(1))
        zoom_reset = QPushButton("Réinitialiser")
        zoom_reset.clicked.connect(self.reset_zoom)
        self.zoom_label = QLabel("Zoom : ajusté")
        zoom_controls = QHBoxLayout()
        zoom_controls.addWidget(QLabel("Zoom :"))
        zoom_controls.addWidget(zoom_out)
        zoom_controls.addWidget(zoom_in)
        zoom_controls.addWidget(zoom_reset)
        zoom_controls.addWidget(self.zoom_label)
        zoom_controls.addStretch()
        open_button = QPushButton("Ouvrir un fichier FITS…")
        open_button.clicked.connect(self.choose_file)
        self.display_method = QComboBox()
        self.display_method.addItem("Linéaire", "linear")
        self.display_method.addItem("Logarithmique", "log")
        self.display_method.addItem("Puissance (0,25)", "power")
        self.display_method.addItem("Racine carrée", "sqrt")
        self.display_method.addItem("Carré", "squared")
        self.display_method.addItem("Asinh", "asinh")
        self.display_method.addItem("Sinh", "sinh")
        self.display_method.addItem("Égalisation d'histogramme", "histogram")
        self.display_method.currentIndexChanged.connect(self.display_method_changed)
        debayer_button = QPushButton("Débayeriser l'image")
        debayer_button.clicked.connect(self.debayer_image)
        debayer_button.setEnabled(False)
        self.debayer_button = debayer_button

        layout = QVBoxLayout(self)
        layout.addWidget(open_button)
        display_controls = QHBoxLayout()
        display_controls.addWidget(QLabel("Échelle d'affichage :"))
        display_controls.addWidget(self.display_method)
        display_controls.addWidget(self.debayer_button)
        layout.addLayout(display_controls)
        layout.addLayout(zoom_controls)
        layout.addWidget(self.file_label)
        layout.addWidget(self.display_notice)
        layout.addWidget(self.image_scroll, 1)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ouvrir une image FITS",
            DATADIR_GUI,
            "FITS (*.fit *.fits)",
        )
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path) -> None:
        try:
            with fits.open(path, memmap=False) as hdul:
                data = hdul[0].data
                header = hdul[0].header.copy()
            if data is None:
                raise ValueError("Le fichier ne contient pas d'image.")
            self.data = np.asarray(data)
            self.header = header
            self.source_path = path
            image = self.to_rgb(self.data, self.header.get("BAYERPAT"))
        except (OSError, ValueError, TypeError) as exc:
            self.file_label.setText(f"{path}\nErreur : {exc}")
            self.source_pixmap = None
            self.data = None
            self.header = None
            self.source_path = None
            self.debayer_button.setEnabled(False)
            self.display_notice.clear()
            self.image.clear()
            return

        self.file_label.setText(str(path))
        self.zoom_factor = 1.0
        if self.data.ndim == 2 and self.header.get("BAYERPAT"):
            self.display_notice.setText(
                "Image couleur débayerisée uniquement pour l'affichage. "
                "Pour enregistrer l'image en couleur, cliquez sur "
                "« Débayeriser l'image »."
            )
        elif self.data.ndim == 3 and self.header.get("DEBAYER"):
            self.display_notice.setText(
                "Image couleur débayerisée et enregistrée dans ce fichier."
            )
        else:
            self.display_notice.clear()
        self.source_pixmap = QPixmap.fromImage(image)
        self.debayer_button.setEnabled(
            self.data.ndim == 2 and bool(self.header.get("BAYERPAT"))
        )
        self.fit_image()

    def debayer_image(self) -> None:
        if self.data is None or self.header is None or self.source_path is None:
            return
        bayer_pattern = self.header.get("BAYERPAT")
        if self.data.ndim != 2 or not bayer_pattern:
            self.file_label.setText(
                f"{self.source_path}\nErreur : motif Bayer absent."
            )
            return
        try:
            debayered = debayer_bilinear(self.data, bayer_pattern)
            header = self.header.copy()
            header["DEBAYER"] = "BILINEAR"
            header.remove("BAYERPAT", ignore_missing=True)
            output = self.source_path.with_name(
                f"{self.source_path.stem}_debayered{self.source_path.suffix}"
            )
            write_fits_image(output, debayered.astype(np.float32), header)
        except (OSError, ValueError, TypeError) as exc:
            self.file_label.setText(f"{self.source_path}\nErreur : {exc}")
            return
        self.load_file(output)

    def display_method_changed(self, index: int) -> None:
        if self.data is not None:
            try:
                self.source_pixmap = QPixmap.fromImage(
                    self.to_rgb(self.data, self.header.get("BAYERPAT"))
                )
                self.fit_image()
            except (ValueError, TypeError) as exc:
                self.file_label.setText(f"Erreur d'affichage : {exc}")

    def change_zoom(self, direction: int) -> None:
        if self.source_pixmap is None:
            return
        self.zoom_factor = min(
            20.0,
            max(0.1, self.zoom_factor * (1.25 if direction > 0 else 0.8)),
        )
        self.zoom_label.setText(f"Zoom : {self.zoom_factor:.2f}×")
        self.fit_image()

    def reset_zoom(self) -> None:
        self.zoom_factor = 1.0
        self.zoom_label.setText("Zoom : ajusté")
        self.fit_image()

    def to_rgb(self, data: np.ndarray, bayer_pattern: object = None) -> QImage:
        method = str(self.display_method.currentData())
        if data.ndim == 2 and bayer_pattern:
            data = debayer_bilinear(data, str(bayer_pattern))
        if data.ndim == 3 and data.shape[0] in (3, 4):
            channels = np.asarray(data[:3], dtype=np.float32)
            planes = [self.normalize(channel, method) for channel in channels]
            rgb = np.moveaxis(np.stack(planes, axis=0), 0, -1)
        elif data.ndim == 2:
            gray = self.normalize(np.asarray(data, dtype=np.float32), method)
            rgb = np.repeat(gray[..., np.newaxis], 3, axis=2)
        else:
            raise ValueError(f"dimensions non supportées : {data.shape}")
        rgb = np.ascontiguousarray((rgb * 255).astype(np.uint8))
        return QImage(
            rgb.data,
            rgb.shape[1],
            rgb.shape[0],
            rgb.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()

    @staticmethod
    def normalize(data: np.ndarray, method: str = "linear") -> np.ndarray:
        finite = data[np.isfinite(data)]
        if finite.size == 0:
            raise ValueError("l'image ne contient aucune valeur finie")
        low, high = np.percentile(finite, (1, 99))
        if high <= low:
            high = low + 1
        normalized = np.clip(
            (np.nan_to_num(data, nan=low) - low) / (high - low), 0, 1
        )
        if method == "linear":
            transformed = normalized
        elif method == "log":
            transformed = np.log1p(9 * normalized) / np.log1p(9)
        elif method == "power":
            transformed = normalized ** 0.25
        elif method == "sqrt":
            transformed = np.sqrt(normalized)
        elif method == "squared":
            transformed = normalized ** 2
        elif method == "asinh":
            transformed = np.arcsinh(10 * normalized) / np.arcsinh(10)
        elif method == "sinh":
            transformed = np.sinh(normalized) / np.sinh(1)
        elif method == "histogram":
            sorted_values = np.sort(normalized.ravel())
            ranks = np.searchsorted(sorted_values, normalized, side="right")
            transformed = ranks / sorted_values.size
        else:
            raise ValueError(f"méthode d'affichage inconnue : {method}")
        return np.clip(transformed, 0, 1)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self.fit_image()

    def fit_image(self) -> None:
        if self.source_pixmap is not None and not self.source_pixmap.isNull():
            viewport_size = self.image_scroll.viewport().size()
            source_size = self.source_pixmap.size()
            fit_scale = min(
                viewport_size.width() / source_size.width(),
                viewport_size.height() / source_size.height(),
            )
            scale = max(0.01, fit_scale * self.zoom_factor)
            target_size = source_size * scale
            self.image.setPixmap(
                self.source_pixmap.scaled(
                    target_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("AstroDataReduc", "OHP")
        self.thread: QThread | None = None
        self.worker: PipelineWorker | None = None
        self.final_output_path: Path | None = None
        self.keep_output_path = False
        self.rgb_selected_files: dict[str, Path] = {}
        self.rgb_selection_context: tuple[str, str, str] | None = None
        self.rgb_files_valid = False
        self.rgb_aligned_valid = False
        self.rgb_alignment_context: tuple[str, str, str] | None = None
        self.rgb_recombination_pending = False
        self.rgb_recombination_timer = QTimer(self)
        self.rgb_recombination_timer.setSingleShot(True)
        self.rgb_recombination_timer.setInterval(50)
        self.rgb_recombination_timer.timeout.connect(
            self.start_rgb_combination
        )
        self.setWindowTitle(f"AstroDataReduc OHP - réduction FITS - v{version_app}")
        self.statusBar().addPermanentWidget(QLabel("© 2026 - @astrosearch42 (Maxime Bertrand)"))
        self.statusBar().setStyleSheet("""
            QStatusBar {
                background-color: #252525;
                color: #aaaaaa;
                border-top: 1px solid #444444;
                font-size: 10px;
            }
        """)
        self.setMinimumSize(1100, 700)
        self.resize(1200, 760)
        self.build_ui()
        saved = self.settings.value("folder/parent")
        if saved and Path(str(saved)).is_dir():
            self.fields["parent"].setText(str(saved))
        saved_output = self.settings.value("folder/final_output")
        saved_keep_output = self.settings.value("folder/keep_output", False)
        self.keep_output_checkbox.setChecked(
            str(saved_keep_output).lower() in {"1", "true", "yes"}
        )
        if saved_output and self.keep_output_checkbox.isChecked():
            self.final_output_path = Path(str(saved_output))
        self.refresh_derived_paths()
        self.update_buttons()

    def build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        options = QWidget()
        options.setMinimumWidth(430)
        options_layout = QVBoxLayout(options)
        folders = QGroupBox("Dossiers de données")
        folders_layout = QVBoxLayout(folders)
        self.fields: dict[str, QLabel] = {}
        parent_title = QLabel("Dossier parent")
        parent_label = QLabel("Non sélectionné")
        parent_label.setWordWrap(True)
        choose_button = QPushButton("Choisir…")
        choose_button.clicked.connect(self.choose_parent_folder)
        parent_row = QHBoxLayout()
        parent_row.addWidget(parent_title)
        parent_row.addStretch()
        parent_row.addWidget(choose_button)
        folders_layout.addLayout(parent_row)
        folders_layout.addWidget(parent_label)
        self.fields["parent"] = parent_label
        parent_separator = QFrame()
        parent_separator.setFrameShape(QFrame.Shape.HLine)
        parent_separator.setFrameShadow(QFrame.Shadow.Sunken)
        folders_layout.addWidget(parent_separator)
        folder_grid = QGridLayout()
        for index, (key, title) in enumerate((
            ("lights", "lights"),
            ("bias", "biases"),
            ("dark", "darks"),
            ("flats", "flats"),
            ("masters", "masters (automatique)"),
            ("process", "process (automatique)"),
        )):
            label = QLabel("Non sélectionné")
            label.setWordWrap(True)
            title_label = QLabel(title)
            row, column = divmod(index, 2)
            content_column = column * 2
            folder_grid.addWidget(title_label, row * 2, content_column)
            folder_grid.addWidget(label, row * 2 + 1, content_column)
            self.fields[key] = label
        column_separator = QFrame()
        column_separator.setFrameShape(QFrame.Shape.VLine)
        column_separator.setStyleSheet(
            "QFrame { border-left: 1px dotted palette(mid); }"
        )
        folder_grid.addWidget(column_separator, 0, 1, 6, 1)
        folder_grid.setColumnStretch(0, 1)
        folder_grid.setColumnStretch(2, 1)
        folders_layout.addLayout(folder_grid)
        output_separator = QFrame()
        output_separator.setFrameShape(QFrame.Shape.HLine)
        output_separator.setFrameShadow(QFrame.Shadow.Sunken)
        folders_layout.addWidget(output_separator)
        output_title = QLabel("Sortie finale")
        output_label = QLabel("Non sélectionné")
        output_label.setWordWrap(True)
        output_button = QPushButton("Choisir…")
        output_button.clicked.connect(self.choose_final_output_folder)
        output_row = QHBoxLayout()
        output_row.addWidget(output_title)
        output_row.addStretch()
        output_row.addWidget(output_button)
        self.keep_output_checkbox = QCheckBox(
            "Garder le même dossier de sortie"
        )
        self.keep_output_checkbox.toggled.connect(self.toggle_keep_output_path)
        output_row.addWidget(self.keep_output_checkbox)
        folders_layout.addLayout(output_row)
        folders_layout.addWidget(output_label)
        self.fields["stack_output"] = output_label
        options_layout.addWidget(folders)

        calibration = QGroupBox("Calibrations à utiliser pour la réduction")
        calibration_layout = QVBoxLayout(calibration)
        self.dark_calibration = QRadioButton("Dark (préféré)")
        self.bias_calibration = QRadioButton("Bias")
        self.no_calibration = QRadioButton("Aucune correction")
        self.dark_calibration.setChecked(True)
        self.flat_calibration = QCheckBox("Flat")
        self.flat_calibration.setChecked(True)
        self.debayer_after_stack = QCheckBox(
            "Débayerisation Bayer (automatique avant alignement)"
        )
        self.debayer_after_stack.setChecked(True)
        self.debayer_after_stack.setEnabled(False)
        self.sound_on_finish = QCheckBox("Son en fin d'action")
        self.sound_on_finish.setChecked(False)
        calibration_layout.addWidget(QLabel("Correction :"))
        calibration_layout.addWidget(self.dark_calibration)
        calibration_layout.addWidget(self.bias_calibration)
        calibration_layout.addWidget(self.no_calibration)
        calibration_layout.addWidget(self.flat_calibration)
        calibration_layout.addWidget(self.debayer_after_stack)
        calibration_layout.addWidget(self.sound_on_finish)
        options_layout.addWidget(calibration)

        actions = QGroupBox("Traitement")
        actions_layout = QVBoxLayout(actions)
        self.buttons: dict[str, QPushButton] = {}
        for key, title in (
            ("masters", "Créer les masters"),
            ("reduce", "Réduire"),
            ("stack", "Stacker"),
            ("full", "Tout le processus"),
        ):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, k=key: self.start(k))
            actions_layout.addWidget(button)
            self.buttons[key] = button
        alignment_row = QHBoxLayout()
        self.buttons["align"] = QPushButton("Aligner")
        self.buttons["align"].clicked.connect(lambda: self.start("align"))
        self.buttons["align_basic"] = QPushButton("Alignement basique")
        self.buttons["align_basic"].clicked.connect(
            lambda: self.start("align_basic")
        )
        alignment_row.addWidget(self.buttons["align"])
        alignment_row.addWidget(self.buttons["align_basic"])
        actions_layout.insertLayout(2, alignment_row)
        options_layout.addWidget(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        options_layout.addWidget(self.progress)
        options_layout.addStretch()

        options_scroll = QScrollArea()
        options_scroll.setWidgetResizable(True)
        options_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        options_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        options_scroll.setWidget(options)
        self.rgb_tab = self.build_rgb_tab()
        self.left_tabs = QTabWidget()
        self.left_tabs.addTab(options_scroll, "Réduction")
        self.left_tabs.addTab(self.rgb_tab, "Recombinaison RGB")

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.viewer = FitsViewer()
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.log, "Console")
        self.right_tabs.addTab(self.viewer, "Visionneuse FITS")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left_tabs)
        splitter.addWidget(self.right_tabs)
        self.left_tabs.setMinimumWidth(430)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([470, 690])
        layout.addWidget(splitter)

    def build_rgb_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()

        folder_row = QHBoxLayout()
        self.rgb_folder = QLineEdit()
        self.rgb_folder.setPlaceholderText("Dossier contenant les 3 FITS empilés")
        self.rgb_folder.textChanged.connect(self.invalidate_rgb_detection)
        choose_button = QPushButton("Choisir…")
        choose_button.clicked.connect(self.choose_rgb_folder)
        folder_row.addWidget(self.rgb_folder, 1)
        folder_row.addWidget(choose_button)
        form.addRow("Dossier des canaux", folder_row)

        self.rgb_filter_keyword = QLineEdit("FLTRNM")
        self.rgb_filter_keyword.textChanged.connect(self.invalidate_rgb_detection)
        self.rgb_filter_keyword.setToolTip(
            "Clé FITS contenant le nom du filtre, par exemple FLTRNM ou FLTR."
        )
        form.addRow("Clé FITS du filtre", self.rgb_filter_keyword)
        self.rgb_mode = QComboBox()
        self.rgb_mode.addItems(
            ["RGB", "HOO", "SHO", "RGB+Ha", "RGB+HOO", "RGB+SHO"]
        )
        self.rgb_mode.currentTextChanged.connect(self.update_narrowband_controls)
        self.rgb_mode.currentTextChanged.connect(self.invalidate_rgb_detection)
        form.addRow("Mode de recombinaison", self.rgb_mode)
        layout.addLayout(form)

        coefficients = QGroupBox("Contribution narrowband")
        coefficients_layout = QVBoxLayout(coefficients)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Préréglage :"))
        self.rgb_preset = QComboBox()
        self.rgb_preset.addItem("Couleurs naturelles dominantes (30 %)", 30)
        self.rgb_preset.addItem("Équilibré (50 %)", 50)
        self.rgb_preset.addItem("Narrowband dominant (70 %)", 70)
        self.rgb_preset.currentIndexChanged.connect(self.apply_narrowband_preset)
        preset_row.addWidget(self.rgb_preset)
        coefficients_layout.addLayout(preset_row)
        self.rgb_sliders: dict[str, QSlider] = {}
        self.rgb_coefficient_labels: dict[str, QLabel] = {}
        for channel, label in (("R", "Rouge"), ("G", "Vert"), ("B", "Bleu")):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(30)
            slider.setTracking(True)
            value_label = QLabel("30 %")
            slider.valueChanged.connect(
                lambda value, key=channel, target=value_label:
                target.setText(f"{value} %")
            )
            slider.valueChanged.connect(self.schedule_rgb_recombination)
            row.addWidget(slider, 1)
            row.addWidget(value_label)
            coefficients_layout.addLayout(row)
            self.rgb_sliders[channel] = slider
            self.rgb_coefficient_labels[channel] = value_label
        layout.addWidget(coefficients)
        self.rgb_coefficients_group = coefficients
        self.update_narrowband_controls(self.rgb_mode.currentText())

        self.detect_button = QPushButton("Détecter les fichiers")
        self.detect_button.clicked.connect(self.detect_rgb_files)
        layout.addWidget(self.detect_button)
        self.rgb_files_status = QLabel(
            "Aucun fichier détecté."
        )
        self.rgb_files_status.setWordWrap(True)
        layout.addWidget(self.rgb_files_status)

        alignment_row = QHBoxLayout()
        self.align_button = QPushButton("Aligner les images")
        self.align_button.clicked.connect(self.start_rgb_alignment)
        self.align_button.setEnabled(False)
        self.rgb_basic_align_button = QPushButton("Alignement basique")
        self.rgb_basic_align_button.clicked.connect(
            lambda: self.start_rgb_alignment(basic=True)
        )
        self.rgb_basic_align_button.setEnabled(False)
        alignment_row.addWidget(self.align_button)
        alignment_row.addWidget(self.rgb_basic_align_button)
        layout.addLayout(alignment_row)

        self.combine_button = QPushButton("Recombiner les canaux")
        self.combine_button.clicked.connect(self.start_rgb_combination)
        self.combine_button.setEnabled(False)
        layout.addWidget(self.combine_button)
        self.rgb_status = QLabel(
            "Filtres reconnus : R, G, B, Ha, H Alpha, O3, OIII, SII, "
            "R Cousins, V Cousins, B Cousins, H Alpha ohp 6565 et "
            "O3 ohp 5007."
        )
        self.rgb_status.setWordWrap(True)
        layout.addWidget(self.rgb_status)
        layout.addStretch()
        return tab

    def choose_rgb_folder(self) -> None:
        previous = self.rgb_folder.text() or DATADIR_GUI
        path = QFileDialog.getExistingDirectory(
            self, "Sélectionner le dossier des canaux RGB", previous
        )
        if path:
            self.rgb_folder.setText(path)

    def invalidate_rgb_detection(self) -> None:
        self.rgb_files_valid = False
        self.rgb_aligned_valid = False
        self.rgb_selected_files = {}
        self.rgb_selection_context = None
        self.rgb_alignment_context = None
        self.rgb_recombination_pending = False
        self.rgb_recombination_timer.stop()
        if self.thread is None and hasattr(self, "combine_button"):
            self.combine_button.setEnabled(False)
            self.align_button.setEnabled(False)
            self.rgb_basic_align_button.setEnabled(False)

    def start_rgb_combination(self) -> None:
        if (
            not self.rgb_files_valid
            or not self.rgb_aligned_valid
        ):
            return
        if self.thread is not None:
            self.rgb_recombination_pending = True
            return
        self.rgb_recombination_pending = False
        directory = Path(self.rgb_folder.text().strip())
        keyword = self.rgb_filter_keyword.text().strip()
        if not directory.is_dir():
            QMessageBox.warning(
                self, "Configuration invalide",
                f"Le dossier des canaux est introuvable : {directory}",
            )
            return
        if not keyword:
            QMessageBox.warning(
                self, "Configuration invalide",
                "Indiquez le nom de la clé FITS du filtre.",
            )
            return
        mode = self.rgb_mode.currentText()
        coefficients = {
            channel: slider.value() / 100
            for channel, slider in self.rgb_sliders.items()
        }
        context = (str(directory.resolve()), keyword, mode)
        selected_files = self.rgb_selected_files
        if self.rgb_alignment_context != context:
            self.rgb_aligned_valid = False
            self.combine_button.setEnabled(False)
            return
        try:
            candidates = detect_channel_candidates(directory, keyword, mode)
        except (OSError, ValueError) as exc:
            self.rgb_files_valid = False
            self.combine_button.setEnabled(False)
            self.log.appendPlainText(f"ERREUR : {exc}")
            self.rgb_files_status.setText(f"Erreur de détection : {exc}")
            return
        if any(len(values) > 1 for values in candidates.values()):
            missing_choices = [
                channel for channel, values in candidates.items()
                if len(values) > 1 and channel not in selected_files
            ]
            if missing_choices:
                self.rgb_files_status.setText(
                    "Détectez les fichiers et sélectionnez un candidat "
                    "pour chaque canal ambigu avant de recombiner."
                )
                self.rgb_files_valid = False
                self.combine_button.setEnabled(False)
                return
        self.start_operation(
            f"combine_{mode.lower()}",
            lambda: [combine_channels(
                directory,
                filter_keyword=keyword,
                mode=mode,
                narrowband_coefficients=coefficients,
                selected_files=selected_files,
            )],
        )

    def schedule_rgb_recombination(self) -> None:
        if not self.rgb_aligned_valid:
            return
        self.rgb_recombination_pending = True
        self.rgb_recombination_timer.start()

    def start_rgb_alignment(self, basic: bool = False) -> None:
        if self.thread is not None or not self.rgb_files_valid:
            return
        directory = Path(self.rgb_folder.text().strip())
        keyword = self.rgb_filter_keyword.text().strip()
        mode = self.rgb_mode.currentText()
        selected_files = self.rgb_selected_files
        self.start_operation(
            f"rgb_align_{'basic_' if basic else ''}{mode.lower()}",
            lambda: [align_channels(
                directory,
                filter_keyword=keyword,
                mode=mode,
                selected_files=selected_files,
                basic=basic,
            )],
        )

    def apply_narrowband_preset(self, index: int) -> None:
        value = int(self.rgb_preset.itemData(index))
        for slider in self.rgb_sliders.values():
            slider.setValue(value)

    def update_narrowband_controls(self, mode: str) -> None:
        narrowband_mode = mode in {"RGB+Ha", "RGB+HOO", "RGB+SHO"}
        self.rgb_coefficients_group.setEnabled(narrowband_mode)
        for channel, slider in self.rgb_sliders.items():
            slider.setEnabled(mode != "RGB+Ha" or channel == "R")

    def detect_rgb_files(self) -> None:
        directory = Path(self.rgb_folder.text().strip())
        keyword = self.rgb_filter_keyword.text().strip()
        mode = self.rgb_mode.currentText()
        if not directory.is_dir():
            QMessageBox.warning(
                self, "Configuration invalide",
                f"Le dossier des canaux est introuvable : {directory}",
            )
            return
        if not keyword:
            QMessageBox.warning(
                self, "Configuration invalide",
                "Indiquez le nom de la clé FITS du filtre.",
            )
            return
        try:
            candidates = detect_channel_candidates(directory, keyword, mode)
        except (OSError, ValueError) as exc:
            self.rgb_files_valid = False
            self.combine_button.setEnabled(False)
            self.rgb_files_status.setText(f"Erreur de détection : {exc}")
            return
        ambiguous = {
            channel: values
            for channel, values in candidates.items()
            if len(values) > 1
        }
        selected_files: dict[str, Path] = {}
        if ambiguous:
            dialog = ChannelSelectionDialog(ambiguous, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.rgb_selected_files = {}
                self.rgb_selection_context = None
                self.rgb_files_valid = False
                self.combine_button.setEnabled(False)
                self.log.appendPlainText(
                    "ERREUR : détection annulée, aucun choix de fichier "
                    "n'a été validé."
                )
                self.rgb_files_status.setText("Détection annulée.")
                return
            selected_files = dialog.selected_files
        self.rgb_selected_files = selected_files
        self.rgb_selection_context = (
            str(directory.resolve()), keyword, mode
        )
        channels: dict[str, tuple[Path, str]] = {}
        for channel, values in candidates.items():
            selected = selected_files.get(channel)
            match = next(
                (
                    value for value in values
                    if selected is not None and value[0].resolve() == selected.resolve()
                ),
                None,
            )
            if match is None and len(values) == 1:
                match = values[0]
            if match is not None:
                channels[channel] = (match[0], match[1])
        self.rgb_files_valid = True
        self.rgb_aligned_valid = False
        self.rgb_alignment_context = None
        self.align_button.setEnabled(self.thread is None)
        self.combine_button.setEnabled(False)
        labels = {"R": "Rouge", "G": "Vert", "B": "Bleu"}
        lines = [f"<b>Mode {mode}</b>"]
        if mode == "RGB+Ha":
            lines.append("Rouge = R + Ha | Vert = G | Bleu = B")
        elif mode == "RGB+HOO":
            lines.append(
                "Rouge = R + Ha | Vert = G + OIII | Bleu = B + OIII"
            )
        elif mode == "RGB+SHO":
            lines.append(
                "Rouge = R + SII | Vert = G + Ha | Bleu = B + OIII"
            )
        for channel in ("R", "G", "B"):
            if channel not in channels:
                source_channel = "G" if mode == "HOO" and channel == "B" else channel
                path, raw_filter = channels[source_channel]
                lines.append(
                    f"{labels[channel]} : {path.name}<br>"
                    f"Header {keyword} : {raw_filter}"
                )
            else:
                path, raw_filter = channels[channel]
                lines.append(
                    f"{labels[channel]} : {path.name}<br>"
                    f"Header {keyword} : {raw_filter}"
                )
        if mode in {"RGB+Ha", "RGB+HOO", "RGB+SHO"}:
            extras = (
                ("HA",)
                if mode == "RGB+Ha"
                else ("HA", "OIII")
                if mode == "RGB+HOO"
                else ("SII", "HA", "OIII")
            )
            for extra in extras:
                path, raw_filter = channels[extra]
                lines.append(
                    f"{extra} : {path.name}<br>"
                    f"Header {keyword} : {raw_filter}"
                )
        self.rgb_files_status.setText("<br><br>".join(lines))

    def choose_parent_folder(self) -> None:
        previous_output = self.path("stack_output")
        previous = self.settings.value(
            "folder/parent",
            DATADIR_GUI
            )
        path = QFileDialog.getExistingDirectory(self, "Sélectionner un dossier", str(previous))
        if path:
            if not self.keep_output_checkbox.isChecked():
                self.final_output_path = Path(path)
            elif previous_output is not None:
                self.final_output_path = previous_output
            self.settings.setValue(
                "folder/final_output",
                str(self.final_output_path)
                if self.final_output_path is not None
                else "",
            )
            self.settings.setValue("folder/parent", path)
            self.fields["parent"].setText(path)
            parent = Path(path)
            try:
                (parent / "masters").mkdir(exist_ok=True)
                (parent / "process").mkdir(exist_ok=True)
            except OSError as exc:
                QMessageBox.critical(
                    self,
                    "Dossiers de travail",
                    f"Impossible de créer masters/process : {exc}",
                )
                return
            self.refresh_derived_paths()
            self.update_buttons()

    def choose_final_output_folder(self) -> None:
        current = self.path("stack_output")
        previous = current if current is not None else DATADIR_GUI
        path = QFileDialog.getExistingDirectory(
            self,
            "Sélectionner le dossier de sortie finale",
            str(previous),
        )
        if path:
            self.final_output_path = Path(path)
            self.keep_output_checkbox.setChecked(True)
            self.settings.setValue("folder/final_output", path)
            self.refresh_derived_paths()
            self.update_buttons()

    def toggle_keep_output_path(self, keep: bool) -> None:
        self.keep_output_path = keep
        self.settings.setValue("folder/keep_output", keep)
        if not keep:
            parent = self.path("parent")
            self.final_output_path = parent
            if parent is not None:
                self.settings.setValue("folder/final_output", str(parent))
            self.refresh_derived_paths()
            self.update_buttons()

    def refresh_derived_paths(self) -> None:
        parent = self.path("parent")
        names = {
            "lights": "lights",
            "bias": "biases",
            "dark": "darks",
            "flats": "flats",
            "masters": "masters",
            "process": "process",
            "stack_output": "recomb_colors",
        }
        for key, name in names.items():
            path = (
                None
                if parent is None
                else self.path("stack_output")
                if key == "stack_output"
                else parent / name
            )
            display_path = self._display_folder_path(key, path)
            self.fields[key].setText(display_path)
            if path is not None:
                self.fields[key].setToolTip(str(path))

    @staticmethod
    def _display_folder_path(key: str, path: Path | None) -> str:
        if path is None:
            return "Non sélectionné"
        if key in {"parent", "stack_output"}:
            return str(path)
        return str(Path("...") / path.parent.name / path.name)

    def path(self, key: str) -> Path | None:
        if key == "parent":
            value = self.fields["parent"].text()
            return None if value == "Non sélectionné" else Path(value)
        parent = self.path("parent")
        if parent is None:
            return None
        if key == "stack_output":
            return self.final_output_path or parent
        names = {
            "lights": "lights",
            "bias": "biases",
            "dark": "darks",
            "flats": "flats",
            "masters": "masters",
            "process": "process",
        }
        for candidate in parent.iterdir() if parent.is_dir() else ():
            if candidate.is_dir() and candidate.name.lower() == names[key].lower():
                return candidate
        return parent / names[key]

    def update_buttons(self) -> None:
        ready = self.path("lights") is not None and self.path("lights").is_dir()
        self.buttons["masters"].setEnabled(
            self.path("masters") is not None
        )
        self.buttons["reduce"].setEnabled(ready and self.path("masters").is_dir())
        self.buttons["align"].setEnabled(ready)
        self.buttons["align_basic"].setEnabled(ready)
        self.buttons["stack"].setEnabled(
            ready and self.path("process").is_dir()
        )
        self.buttons["full"].setEnabled(
            ready
            and self.path("masters") is not None
        )

    def start(self, operation: str) -> None:
        if self.thread is not None:
            return
        try:
            job = self.make_job(operation)
        except (ValueError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Configuration invalide", str(exc))
            return
        if job is None:
            return
        self.start_operation(operation, job)

    def start_operation(self, operation: str, job: Callable[[], object]) -> None:
        self.progress.setRange(0, 0)
        self.set_busy(True)
        self.combine_button.setEnabled(False)
        self.current_operation = operation
        self.log.appendPlainText(f">>> {operation}")
        self.thread = QThread(self)
        self.worker = PipelineWorker(job)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.message.connect(self.log.appendPlainText)
        self.worker.finished.connect(self.operation_finished)
        self.worker.failed.connect(self.operation_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.thread_finished)
        self.thread.start()

    def make_job(self, operation: str) -> Callable[[], object] | None:
        lights = self.path("lights")
        masters = self.path("masters")
        if operation not in {"masters", "full"} and (
            lights is None or masters is None
        ):
            raise ValueError("Sélectionnez les dossiers lights et masters.")
        if operation in {"masters", "full"}:
            aligner = align_images
            if operation == "full":
                alignment_choice = QMessageBox(self)
                alignment_choice.setWindowTitle("Méthode d'alignement")
                alignment_choice.setText(
                    "Choisissez la méthode d'alignement pour le processus complet."
                )
                advanced_button = alignment_choice.addButton(
                    "Alignement actuel",
                    QMessageBox.ButtonRole.AcceptRole,
                )
                basic_button = alignment_choice.addButton(
                    "Alignement basique",
                    QMessageBox.ButtonRole.AcceptRole,
                )
                alignment_choice.addButton(
                    QMessageBox.StandardButton.Cancel
                )
                alignment_choice.exec()
                clicked_button = alignment_choice.clickedButton()
                if clicked_button is None:
                    return None
                if clicked_button is basic_button:
                    aligner = align_images_basic
                elif clicked_button is not advanced_button:
                    return None
            master_job, masters = self.make_master_job(lights, masters)
            if operation == "masters":
                return master_job
            assert lights is not None
            process = self.path("process")
            output = self.path("stack_output")
            assert process is not None and output is not None
            debayer = self.debayer_after_stack.isChecked()

            def run_full_pipeline() -> list[Path]:
                print("Étape 1/4 : création des masters")
                master_job()
                files = [
                    path for path in iter_fits_files(lights)
                ]
                print("Étape 2/4 : réduction des images")
                reduce_images(
                    files,
                    masters,
                    output_dir=process,
                    calibration=(
                        "dark"
                        if self.dark_calibration.isChecked()
                        else "bias"
                        if self.bias_calibration.isChecked()
                        else None
                    ),
                    use_flat=self.flat_calibration.isChecked(),
                )
                print("Étape 3/4 : alignement des images")
                aligner(process, output_dir=process)
                print("Étape 4/4 : stacking")
                return stack_images(
                    process,
                    output,
                    debayer=debayer,
                )

            return run_full_pipeline
        assert lights is not None and masters is not None
        if operation == "reduce":
            process = self.path("process")
            assert process is not None
            files = iter_fits_files(lights)
            return lambda: reduce_images(
                files,
                masters,
                output_dir=process,
                calibration=(
                    "dark"
                    if self.dark_calibration.isChecked()
                    else "bias"
                    if self.bias_calibration.isChecked()
                    else None
                ),
                use_flat=self.flat_calibration.isChecked(),
            )
        if operation in {"align", "align_basic"}:
            process = self.path("process")
            assert process is not None
            aligner = align_images_basic if operation == "align_basic" else align_images
            return lambda: aligner(process, output_dir=process)
        process = self.path("process")
        output = self.path("stack_output")
        assert process is not None and output is not None
        return lambda: stack_images(
            process,
            output,
            debayer=self.debayer_after_stack.isChecked(),
        )

    def make_master_job(
        self, lights: Path | None, masters: Path | None
    ) -> tuple[Callable[[], list[str]], Path]:
        bias = self.path("bias")
        dark = self.path("dark")
        flats = self.path("flats")
        use_dark = self.dark_calibration.isChecked()
        use_bias = self.bias_calibration.isChecked()
        use_flat = self.flat_calibration.isChecked()
        if masters is None:
            raise ValueError("Le dossier des masters n'est pas sélectionné.")
        if use_bias and (bias is None or not bias.is_dir()):
            raise FileNotFoundError(
                f"Le dossier des bias est requis mais absent : {bias}"
            )
        if use_flat and (flats is None or not flats.is_dir()):
            raise FileNotFoundError(
                f"Le dossier des flats est requis mais absent : {flats}"
            )
        if use_bias and not iter_fits_files(bias):
            raise FileNotFoundError(
                f"Aucun fichier bias FITS trouvé dans {bias}."
            )
        if use_flat and not iter_fits_files(flats):
            raise FileNotFoundError(
                f"Aucun fichier flat FITS trouvé dans {flats}."
            )
        if use_dark:
            if dark is None or not dark.is_dir():
                raise FileNotFoundError(
                    f"Le dossier des darks est requis mais absent : {dark}"
                )
            if not iter_fits_files(dark):
                raise FileNotFoundError(
                    f"Aucun fichier dark FITS trouvé dans {dark}."
                )
        existing = existing_master_files_by_type(masters)
        decisions: dict[str, bool] = {}
        master_types = []
        if use_bias:
            master_types.append("bias")
        if use_flat:
            master_types.append("flat")
        if use_dark:
            master_types.append("dark")
        for master_type in master_types:
            label = master_type
            if existing[master_type]:
                answer = QMessageBox.question(
                    self,
                    "Master existant",
                    f"Le master {label} existe déjà. Voulez-vous le recréer ?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                decisions[master_type] = answer == QMessageBox.Yes
            else:
                decisions[master_type] = True
        masters.mkdir(parents=True, exist_ok=True)

        def create_masters() -> list[str]:
            bias_file = None
            if use_bias and decisions["bias"]:
                bias_file = make_master_offset(bias, masters)
            elif use_bias:
                bias_file = fits_path(masters, "master_bias")
            if use_flat and decisions["flat"]:
                make_master_flat(flats, bias_file, masters)
            if use_dark and decisions["dark"]:
                make_master_dark(dark, masters)
            return [] if bias_file is None else [str(bias_file)]

        return create_masters, masters

    def set_busy(self, busy: bool) -> None:
        for button in self.buttons.values():
            button.setEnabled(not busy)
        self.detect_button.setEnabled(not busy)
        self.align_button.setEnabled(not busy and self.rgb_files_valid)
        self.rgb_basic_align_button.setEnabled(not busy and self.rgb_files_valid)
        self.combine_button.setEnabled(not busy and self.rgb_aligned_valid)

    @Slot(object)
    def operation_finished(self, result: object) -> None:
        if self.current_operation.startswith("rgb_align_"):
            self.rgb_aligned_valid = True
            self.rgb_alignment_context = (
                str(Path(self.rgb_folder.text().strip()).resolve()),
                self.rgb_filter_keyword.text().strip(),
                self.rgb_mode.currentText(),
            )
        count = len(result) if isinstance(result, list) else 1
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.log.appendPlainText(f"Terminé : {count} produit(s).")
        if self.sound_on_finish.isChecked():
            QApplication.beep()
        if isinstance(result, list):
            fits_results = [Path(item) for item in result if Path(item).is_file()]
            if fits_results:
                self.viewer.load_file(fits_results[-1])
                self.right_tabs.setCurrentWidget(self.viewer)

    @Slot(str)
    def operation_failed(self, message: str) -> None:
        if self.current_operation.startswith("rgb_align_"):
            self.rgb_aligned_valid = False
            self.rgb_alignment_context = None
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log.appendPlainText(f"ERREUR : {message}")
        QMessageBox.critical(self, "Échec du traitement", message)

    @Slot()
    def thread_finished(self) -> None:
        if self.thread is not None:
            self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self.set_busy(False)
        self.update_buttons()
        if self.rgb_recombination_pending and self.rgb_aligned_valid:
            self.rgb_recombination_timer.start()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
