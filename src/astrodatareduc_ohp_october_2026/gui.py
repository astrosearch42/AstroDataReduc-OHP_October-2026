"""Application Qt6 pour le pipeline de réduction FITS de l'OHP."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import redirect_stdout

from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .align_images import align_images
from .make_masters import make_master_dark, make_master_flat, make_master_offset
from .reduce_fits import reduce_images
from .stack_images import stack_images
from .Utils.Utils import (
    MASTER_DIR,
    Path,
    debayer_bilinear,
    existing_master_files_by_type,
    fits,
    fits_path,
    iter_fits_files,
    np,
    sys,
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


class FitsViewer(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.file_label = QLabel("Aucun fichier FITS chargé")
        self.file_label.setWordWrap(True)
        self.display_notice = QLabel()
        self.display_notice.setWordWrap(True)
        self.image = QLabel("Sélectionnez un fichier FITS à afficher.")
        self.source_pixmap: QPixmap | None = None
        self.data: np.ndarray | None = None
        self.header: fits.Header | None = None
        self.source_path: Path | None = None
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(320, 240)
        self.image.setScaledContents(False)
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
        layout.addWidget(self.file_label)
        layout.addWidget(self.display_notice)
        layout.addWidget(self.image, 1)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ouvrir une image FITS",
            "C:/Users/bertr/Documents/Coding/UGA/M2/AstroObs/AstroDataReduc-OHP_October-2026/data",
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
            self.image.setPixmap(
                self.source_pixmap.scaled(
                    self.image.size(),
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
        self.setWindowTitle("AstroDataReduc OHP - réduction FITS")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 760)
        self.build_ui()
        saved = self.settings.value("folder/parent")
        if saved and Path(str(saved)).is_dir():
            self.fields["parent"].setText(str(saved))
            self.refresh_derived_paths()
        self.update_buttons()

    def build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)

        options = QWidget()
        options.setMinimumWidth(390)
        options_layout = QVBoxLayout(options)
        folders = QGroupBox("Dossiers de données")
        form = QFormLayout(folders)
        self.fields: dict[str, QLabel] = {}
        row = QHBoxLayout()
        parent_label = QLabel("Non sélectionné")
        parent_label.setWordWrap(True)
        choose_button = QPushButton("Choisir…")
        choose_button.clicked.connect(self.choose_parent_folder)
        row.addWidget(parent_label, 1)
        row.addWidget(choose_button)
        form.addRow("Dossier parent", row)
        self.fields["parent"] = parent_label
        for key, title in (
            ("lights", "lights"),
            ("bias", "biases"),
            ("dark", "darks"),
            ("flats", "flats"),
            ("masters", "masters (automatique)"),
            ("process", "process (automatique)"),
            ("stack_output", "Sortie finale (parent)"),
        ):
            label = QLabel("Non sélectionné")
            label.setWordWrap(True)
            form.addRow(title, label)
            self.fields[key] = label
        options_layout.addWidget(folders)

        calibration = QGroupBox("Calibrations à utiliser pour la réduction")
        calibration_layout = QHBoxLayout(calibration)
        self.dark_calibration = QRadioButton("Dark (préféré)")
        self.bias_calibration = QRadioButton("Bias")
        self.dark_calibration.setChecked(True)
        self.debayer_after_stack = QCheckBox("Débayeriser après empilement")
        self.sound_on_finish = QCheckBox("Son en fin d'action")
        self.sound_on_finish.setChecked(True)
        calibration_layout.addWidget(QLabel("Correction :"))
        calibration_layout.addWidget(self.dark_calibration)
        calibration_layout.addWidget(self.bias_calibration)
        calibration_layout.addWidget(self.debayer_after_stack)
        calibration_layout.addWidget(self.sound_on_finish)
        options_layout.addWidget(calibration)

        actions = QGroupBox("Traitement")
        actions_layout = QHBoxLayout(actions)
        self.buttons: dict[str, QPushButton] = {}
        for key, title in (
            ("masters", "Créer les masters"),
            ("reduce", "Réduire"),
            ("align", "Aligner"),
            ("stack", "Stacker"),
            ("full", "Tout le processus"),
        ):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, k=key: self.start(k))
            actions_layout.addWidget(button)
            self.buttons[key] = button
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

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.viewer = FitsViewer()
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.log, "Console")
        self.right_tabs.addTab(self.viewer, "Visionneuse FITS")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(options_scroll)
        splitter.addWidget(self.right_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([360, 700])
        layout.addWidget(splitter)

    def choose_parent_folder(self) -> None:
        previous = self.settings.value("folder/parent", str(Path.home()))
        path = QFileDialog.getExistingDirectory(self, "Sélectionner un dossier", str(previous))
        if path:
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

    def refresh_derived_paths(self) -> None:
        parent = self.path("parent")
        names = {
            "lights": "lights",
            "bias": "biases",
            "dark": "darks",
            "flats": "flats",
            "masters": "masters",
            "process": "process",
            "stack_output": "",
        }
        for key, name in names.items():
            path = None if parent is None else parent / name if name else parent
            self.fields[key].setText(str(path) if path is not None else "Non sélectionné")

    def path(self, key: str) -> Path | None:
        if key == "parent":
            value = self.fields["parent"].text()
            return None if value == "Non sélectionné" else Path(value)
        parent = self.path("parent")
        if parent is None:
            return None
        if key == "stack_output":
            return parent
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
            self.path("bias") is not None
            and self.path("bias").is_dir()
            and self.path("flats") is not None
            and self.path("flats").is_dir()
        )
        self.buttons["reduce"].setEnabled(ready and self.path("masters").is_dir())
        self.buttons["align"].setEnabled(ready)
        self.buttons["stack"].setEnabled(
            ready and self.path("process").is_dir()
        )
        self.buttons["full"].setEnabled(
            ready
            and self.path("bias") is not None
            and self.path("bias").is_dir()
            and self.path("flats") is not None
            and self.path("flats").is_dir()
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
        self.progress.setRange(0, 0)
        self.set_busy(True)
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
            master_job, masters = self.make_master_job(lights, masters)
            if operation == "masters":
                return master_job
            self.fields["masters"].setText(str(masters))
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
                    calibration="dark" if self.dark_calibration.isChecked() else "bias",
                )
                print("Étape 3/4 : alignement des images")
                align_images(process, output_dir=process)
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
                    "dark" if self.dark_calibration.isChecked() else "bias"
                ),
            )
        if operation == "align":
            process = self.path("process")
            assert process is not None
            return lambda: align_images(process, output_dir=process)
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
        masters = masters or (
            lights / "masters" if lights is not None else Path(MASTER_DIR)
        )
        if bias is None or flats is None:
            raise ValueError("Sélectionnez les dossiers bias et flats.")
        if not bias.is_dir():
            raise FileNotFoundError(
                f"Le dossier des bias est requis mais absent : {bias}"
            )
        if not flats.is_dir():
            raise FileNotFoundError(
                f"Le dossier des flats est requis mais absent : {flats}"
            )
        if not iter_fits_files(bias):
            raise FileNotFoundError(
                f"Aucun fichier bias FITS trouvé dans {bias}."
            )
        if not iter_fits_files(flats):
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
        master_types = ["bias", "flat"]
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
        self.fields["masters"].setText(str(masters))

        def create_masters() -> list[str]:
            if decisions["bias"]:
                bias_file = make_master_offset(bias, masters)
            else:
                bias_file = fits_path(masters, "master_bias")
            if decisions["flat"]:
                make_master_flat(flats, bias_file, masters)
            if use_dark and decisions["dark"]:
                make_master_dark(dark, masters)
            return [str(bias_file)]

        return create_masters, masters

    def set_busy(self, busy: bool) -> None:
        for button in self.buttons.values():
            button.setEnabled(not busy)

    @Slot(object)
    def operation_finished(self, result: object) -> None:
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


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
