"""Background worker utilities (QThread) for heavy document operations."""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QProgressDialog


class TaskWorker(QThread):
    """Run a callable off the GUI thread with cooperative cancel & progress."""

    progress = Signal(int, int, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def report(self, current: int, total: int, message: str = "") -> bool:
        self.progress.emit(int(current), int(total), str(message))
        return not self._cancelled

    def run(self):
        try:
            res = self._fn(self)
            self.succeeded.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)


def run_in_background(parent, title: str, initial_label: str, fn, *,
                      maximum: int = 0, cancelable: bool = True):
    """Execute *fn(worker)* on a QThread while showing a responsive progress dialog.

    Returns ``(ok, result_or_error)``.
    """
    from PySide6.QtCore import QEventLoop

    prog = QProgressDialog(initial_label, "Batal" if cancelable else "",
                           0, maximum, parent)
    prog.setWindowTitle(title)
    prog.setWindowModality(Qt.WindowModal)
    prog.setMinimumDuration(0)
    if not cancelable:
        prog.setCancelButton(None)
    prog.show()

    worker = TaskWorker(fn, parent)
    outcome = {"ok": False, "value": None, "done": False}
    loop = QEventLoop(parent)

    def on_progress(cur, total, msg):
        if total != prog.maximum():
            prog.setMaximum(total)
        prog.setValue(cur)
        if msg:
            prog.setLabelText(msg)

    def on_ok(val):
        outcome["ok"] = True
        outcome["value"] = val
        outcome["done"] = True
        loop.quit()

    def on_fail(err):
        outcome["ok"] = False
        outcome["value"] = err
        outcome["done"] = True
        loop.quit()

    worker.progress.connect(on_progress)
    worker.succeeded.connect(on_ok)
    worker.failed.connect(on_fail)
    if cancelable:
        prog.canceled.connect(worker.cancel)

    worker.start()
    if not outcome["done"]:
        loop.exec()
    worker.wait()
    prog.close()
    return outcome["ok"], outcome["value"]
