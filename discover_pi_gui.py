#!/usr/bin/env python3
"""PySide6 GUI for Raspberry Pi discovery."""

from __future__ import annotations

import sys
import subprocess
import traceback
from ctypes.util import find_library
from os import environ
from shutil import which

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from discover_pi import (
    DEFAULT_HOSTNAME,
    SSH_PORT,
    DiscoveryProgress,
    DiscoverySummary,
    discover,
)


class DiscoveryWorker(QThread):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()

    def run(self) -> None:
        try:
            summary = discover(
                target_hostname=DEFAULT_HOSTNAME,
                cli_networks=None,
                timeout=0.4,
                workers=128,
                show_all=False,
                progress_callback=self.progress.emit,
            )
        except Exception as exc:  # pragma: no cover - UI error path
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self.failed.emit(detail)
            return
        self.finished.emit(summary)


class DiscoveryWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.worker: DiscoveryWorker | None = None
        self.setWindowTitle("Raspberry Pi Discovery")
        self.resize(720, 420)

        root = QWidget()
        self.setCentralWidget(root)

        layout = QGridLayout(root)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)

        self.discover_button = QPushButton("Discover")
        self.discover_button.setDefault(True)
        self.discover_button.clicked.connect(self.start_discovery)

        title_label = QLabel("Find Raspberry Pis on this network")
        title_label.setObjectName("titleLabel")

        self.status_label = QLabel("Ready")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        layout.addWidget(title_label, 0, 0)
        layout.addWidget(self.discover_button, 0, 1)
        layout.addWidget(self.status_label, 1, 0, 1, 2)
        layout.addWidget(self.progress_bar, 2, 0, 1, 2)

        self.results_table = QTableWidget(0, 6)
        self.results_table.setHorizontalHeaderLabels(
            ["IP", "Hostname", "MAC", "SSH", "Confidence", "Evidence"]
        )
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.results_table, 3, 0, 1, 2)

        self.footer_label = QLabel("No scan has run yet.")
        self.footer_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.footer_label, 4, 0, 1, 2)

        layout.setColumnStretch(0, 1)
        layout.setRowStretch(3, 1)

    def start_discovery(self) -> None:
        self.results_table.setRowCount(0)
        self.footer_label.setText("Discovery in progress.")
        self.status_label.setText("Starting discovery")
        self.progress_bar.setRange(0, 0)
        self.set_inputs_enabled(False)

        self.worker = DiscoveryWorker()
        self.worker.progress.connect(self.handle_progress)
        self.worker.finished.connect(self.handle_finished)
        self.worker.failed.connect(self.handle_failed)
        self.worker.start()

    def handle_progress(self, progress: DiscoveryProgress) -> None:
        self.status_label.setText(f"{progress.phase}: {progress.message}")
        if progress.total > 0:
            self.progress_bar.setRange(0, progress.total)
            self.progress_bar.setValue(progress.completed)
        else:
            self.progress_bar.setRange(0, 0)

    def handle_finished(self, summary: DiscoverySummary) -> None:
        self.populate_results(summary)
        self.progress_bar.setRange(0, max(summary.scanned_hosts, 1))
        self.progress_bar.setValue(summary.scanned_hosts)
        self.status_label.setText("Done")
        self.footer_label.setText(self.summary_text(summary))
        self.set_inputs_enabled(True)
        self.worker = None

    def handle_failed(self, message: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText("Discovery failed")
        self.footer_label.setText(message)
        self.set_inputs_enabled(True)
        self.worker = None
        QMessageBox.critical(self, "Discovery failed", message)

    def set_inputs_enabled(self, enabled: bool) -> None:
        self.discover_button.setEnabled(enabled)

    def populate_results(self, summary: DiscoverySummary) -> None:
        visible = _visible_results(summary)
        self.results_table.setRowCount(len(visible))
        for row, result in enumerate(visible):
            host = result.host
            values = [
                host.ip,
                host.hostname or host.resolved_from or "-",
                host.mac or "-",
                "reachable" if SSH_PORT in host.open_ports else "-",
                result.confidence,
                ", ".join(result.evidence) or "-",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 4:
                    item.setForeground(_confidence_color(result.confidence))
                self.results_table.setItem(row, column, item)
        self.results_table.resizeRowsToContents()

    def summary_text(self, summary: DiscoverySummary) -> str:
        visible = _visible_results(summary)
        network_count = len(summary.scanned_networks)
        subject = f"Found {len(visible)} Raspberry Pi candidate"
        if len(visible) != 1:
            subject += "s"
        return (
            f"{subject}. Scanned {summary.scanned_hosts} hosts "
            f"across {network_count} networks."
        )


def _visible_results(summary: DiscoverySummary) -> list:
    return [result for result in summary.results if result.score > 0]


def _confidence_color(confidence: str) -> QColor:
    if confidence == "high":
        return QColor("#1b7f3a")
    if confidence == "medium":
        return QColor("#9a6a00")
    return QColor("#666666")


def main() -> int:
    if _missing_xcb_cursor():
        _show_startup_error(_xcb_cursor_error_message())
        return 1

    app = QApplication(sys.argv)
    window = DiscoveryWindow()
    window.show()
    return app.exec()


def _missing_xcb_cursor() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    if environ.get("QT_QPA_PLATFORM") and environ["QT_QPA_PLATFORM"] != "xcb":
        return False
    if environ.get("WAYLAND_DISPLAY") and not environ.get("DISPLAY"):
        return False
    return find_library("xcb-cursor") is None


def _xcb_cursor_error_message() -> str:
    return (
        "Missing Linux GUI dependency: libxcb-cursor.so.0\n\n"
        "Install the package that provides it, for example:\n\n"
        "Debian/Ubuntu:\n"
        "  sudo apt install libxcb-cursor0\n\n"
        "Fedora:\n"
        "  sudo dnf install xcb-util-cursor\n\n"
        "Arch:\n"
        "  sudo pacman -S xcb-util-cursor"
    )


def _show_startup_error(message: str) -> None:
    print(message, file=sys.stderr)
    commands = [
        ["zenity", "--error", "--title", "Raspberry Pi Discovery", "--text", message],
        ["kdialog", "--title", "Raspberry Pi Discovery", "--error", message],
        ["xmessage", "-center", "-title", "Raspberry Pi Discovery", message],
    ]
    for command in commands:
        if which(command[0]) is None:
            continue
        try:
            subprocess.run(command, check=False, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            continue
        return


if __name__ == "__main__":
    raise SystemExit(main())
