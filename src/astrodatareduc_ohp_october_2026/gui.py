"""Qt6 application for the OHP FITS reduction pipeline."""

from __future__ import annotations

import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSettings, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
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
    QVBoxLayout,
    QWidget,
)

from .Align_images import align_images
from .Make_Masters import make_master_dark, make_master_flat, make_master_offset
from .Reduce_FITS import reduce_images
from .Stack_images import stack_images


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
            with redirect_stdout(_WorkerOutput(self.message)):
                result = self.operation()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit(result)


class _WorkerOutput:
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings("AstroDataReduc", "OHP")
        self.thread: QThread | None = None
        self.worker: PipelineWorker | None = None
        self.setWindowTitle("AstroDataReduc OHP - réduction FITS")
        self.resize(900, 650)
        self._build_ui()
        for key, label in self.fields.items():
            saved = self.settings.value(f"folder/{key}")
            if saved and Path(str(saved)).is_dir():
                label.setText(str(saved))
        self._update_buttons()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        folders = QGroupBox("Dossiers de données")
        form = QFormLayout(folders)
        self.fields: dict[str, QLabel] = {}
        for key, title in (
            ("lights", "Lights (images scientifiques)"),
            ("bias", "Bias / offsets"),
            ("dark", "Darks (optionnel)"),
            ("flats", "Flats"),
            ("masters", "Masters"),
            ("stack_output", "Sortie des stacks"),
        ):
            row = QHBoxLayout()
            label = QLabel("Non sélectionné")
            label.setWordWrap(True)
            button = QPushButton("Choisir…")
            button.clicked.connect(lambda _checked=False, k=key: self._choose_folder(k))
            row.addWidget(label, 1)
            row.addWidget(button)
            form.addRow(title, row)
            self.fields[key] = label
        layout.addWidget(folders)

        actions = QGroupBox("Traitement")
        actions_layout = QHBoxLayout(actions)
        self.buttons: dict[str, QPushButton] = {}
        for key, title in (
            ("masters", "Créer les masters"),
            ("reduce", "Réduire"),
            ("align", "Aligner"),
            ("stack", "Stacker"),
        ):
            button = QPushButton(title)
            button.clicked.connect(lambda _checked=False, k=key: self._start(k))
            actions_layout.addWidget(button)
            self.buttons[key] = button
        layout.addWidget(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        layout.addWidget(self.log, 1)

    def _choose_folder(self, key: str) -> None:
        previous = self.settings.value(f"folder/{key}", str(Path.home()))
        path = QFileDialog.getExistingDirectory(self, "Sélectionner un dossier", str(previous))
        if path:
            self.settings.setValue(f"folder/{key}", path)
            self.fields[key].setText(path)
            self._update_buttons()

    def _path(self, key: str) -> Path | None:
        value = self.fields[key].text()
        return None if value == "Non sélectionné" else Path(value)

    def _update_buttons(self) -> None:
        ready = self._path("lights") is not None
        self.buttons["masters"].setEnabled(
            self._path("bias") is not None and self._path("flats") is not None
        )
        self.buttons["reduce"].setEnabled(ready and self._path("masters") is not None)
        self.buttons["align"].setEnabled(ready)
        self.buttons["stack"].setEnabled(
            ready and self._path("stack_output") is not None
        )

    def _start(self, operation: str) -> None:
        if self.thread is not None:
            return
        try:
            job = self._make_job(operation)
        except (ValueError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Configuration invalide", str(exc))
            return
        self.progress.setRange(0, 0)
        self._set_busy(True)
        self.log.appendPlainText(f">>> {operation}")
        self.thread = QThread(self)
        self.worker = PipelineWorker(job)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.message.connect(self.log.appendPlainText)
        self.worker.finished.connect(self._operation_finished)
        self.worker.failed.connect(self._operation_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    def _make_job(self, operation: str) -> Callable[[], object]:
        lights = self._path("lights")
        masters = self._path("masters")
        if operation != "masters" and (lights is None or masters is None):
            raise ValueError("Sélectionnez les dossiers lights et masters.")
        if operation == "masters":
            bias = self._path("bias")
            flats = self._path("flats")
            dark_dir = self._path("dark")
            masters = masters or lights / "masters"
            if bias is None or flats is None:
                raise ValueError("Sélectionnez les dossiers bias et flats.")
            masters.mkdir(parents=True, exist_ok=True)
            self.fields["masters"].setText(str(masters))

            def create_masters() -> list[str]:
                bias_file = make_master_offset(bias, masters)
                make_master_flat(flats, bias_file, masters)
                if dark_dir is not None:
                    make_master_dark(dark_dir, bias_file, masters)
                return [str(bias_file)]

            return create_masters
        assert lights is not None and masters is not None
        if operation == "reduce":
            files = sorted(
                path for path in lights.glob("*.fits")
                if "_reduced" not in path.stem.lower()
                and "_aligned" not in path.stem.lower()
            )
            dark = masters / "master_dark.fits"
            if not dark.exists():
                dark = None
            return lambda: reduce_images(files, dark, masters)
        if operation == "align":
            return lambda: align_images(lights)
        output = self._path("stack_output")
        if output is None:
            raise ValueError("Sélectionnez le dossier de sortie des stacks.")
        return lambda: stack_images(lights, output)

    def _set_busy(self, busy: bool) -> None:
        for button in self.buttons.values():
            button.setEnabled(not busy)

    @Slot(object)
    def _operation_finished(self, result: object) -> None:
        count = len(result) if isinstance(result, list) else 1
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.log.appendPlainText(f"Terminé : {count} produit(s).")

    @Slot(str)
    def _operation_failed(self, message: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log.appendPlainText(f"ERREUR : {message}")
        QMessageBox.critical(self, "Échec du traitement", message)

    @Slot()
    def _thread_finished(self) -> None:
        if self.thread is not None:
            self.thread.deleteLater()
        self.thread = None
        self.worker = None
        self._set_busy(False)
        self._update_buttons()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
