#!/usr/bin/env python3
"""devpip GUI: PySide6 front-end (Catppuccin Mocha) for devpip.py. Run: python devpip_gui.py"""
import subprocess, sys
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRegularExpression, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
                               QAbstractItemView)

import devpip as core

# ---------------- Catppuccin Mocha ----------------
P = dict(rosewater="#f5e0dc", flamingo="#f2cdcd", pink="#f5c2e7", mauve="#cba6f7", red="#f38ba8", maroon="#eba0ac",
         peach="#fab387", yellow="#f9e2af", green="#a6e3a1", teal="#94e2d5", sky="#89dceb", sapphire="#74c7ec",
         blue="#89b4fa", lavender="#b4befe", text="#cdd6f4", subtext1="#bac2de", subtext0="#a6adc8",
         overlay2="#9399b2", overlay1="#7f849c", overlay0="#6c7086", surface2="#585b70", surface1="#45475a",
         surface0="#313244", base="#1e1e2e", mantle="#181825", crust="#11111b")
MONO = "JetBrains Mono, Cascadia Mono, Consolas, monospace"

QSS = """
* { font-family: 'Segoe UI', sans-serif; font-size: 13px; color: @text; }
QMainWindow, QWidget#root { background: @base; }
QTabWidget::pane { border: 1px solid @surface0; background: @base; border-radius: 8px; top: -1px; }
QTabBar::tab { background: @mantle; color: @subtext0; padding: 8px 18px; border: 1px solid @surface0;
               border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px; }
QTabBar::tab:selected { background: @base; color: @mauve; }
QTabBar::tab:hover:!selected { color: @text; }
QLineEdit, QComboBox, QListWidget, QTableWidget, QPlainTextEdit, QTextEdit {
    background: @mantle; border: 1px solid @surface0; border-radius: 6px; padding: 5px;
    selection-background-color: @surface2; selection-color: @text; }
QLineEdit:focus, QComboBox:focus { border: 1px solid @mauve; }
QPlainTextEdit#log, QPlainTextEdit#flags, QPlainTextEdit#editor { font-family: @mono; font-size: 13px; }
QPlainTextEdit#log { background: @crust; }
QPushButton { background: @surface0; border: 1px solid @surface1; border-radius: 6px; padding: 6px 14px; }
QPushButton:hover { background: @surface1; border-color: @mauve; }
QPushButton:disabled { color: @overlay0; background: @mantle; border-color: @surface0; }
QPushButton#primary { background: @mauve; color: @crust; border: none; font-weight: 600; }
QPushButton#primary:hover { background: @lavender; }
QPushButton#primary:disabled { background: @surface1; color: @overlay0; }
QPushButton#danger { color: @red; }
QPushButton#danger:hover { border-color: @red; }
QListWidget::item { padding: 6px 8px; border-radius: 4px; }
QListWidget::item:selected, QTableWidget::item:selected { background: @surface1; color: @text; }
QListWidget::item:hover { background: @surface0; }
QHeaderView::section { background: @surface0; color: @subtext1; border: none; padding: 6px; font-weight: 600; }
QTableWidget { gridline-color: @surface0; alternate-background-color: @base; }
QLabel#title { font-size: 20px; font-weight: 700; color: @mauve; }
QLabel#chip { background: @surface0; border-radius: 10px; padding: 4px 12px; color: @green; }
QLabel#chip[bad="true"] { color: @red; }
QLabel#muted { color: @overlay1; }
QSplitter::handle { background: @surface0; height: 3px; }
QScrollBar:vertical { background: @mantle; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: @surface1; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: @surface2; }
QScrollBar:horizontal { background: @mantle; height: 10px; }
QScrollBar::handle:horizontal { background: @surface1; border-radius: 5px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QComboBox QAbstractItemView { background: @mantle; selection-background-color: @surface1; border: 1px solid @surface1; }
QToolTip { background: @surface0; color: @text; border: 1px solid @surface1; }
"""


def stylesheet():
    s = QSS.replace("@mono", MONO)
    for k in sorted(P, key=len, reverse=True):
        s = s.replace("@" + k, P[k])
    return s


# ---------------- syntax highlighting ----------------
def fmt(color, italic=False, bold=False):
    f = QTextCharFormat()
    f.setForeground(QColor(P[color]))
    f.setFontItalic(italic)
    if bold:
        f.setFontWeight(QFont.Bold)
    return f


KEYWORDS = ("alignas alignof asm auto break case catch class const constexpr const_cast continue decltype default "
            "delete do dynamic_cast else enum explicit export extern for friend goto if inline mutable namespace "
            "new noexcept operator private protected public register reinterpret_cast return sizeof static "
            "static_assert static_cast struct switch template this throw try typedef typeid typename union using "
            "virtual volatile while").split()
TYPES = ("void int char short long float double bool signed unsigned size_t ssize_t wchar_t int8_t int16_t int32_t "
         "int64_t uint8_t uint16_t uint32_t uint64_t string vector map set unordered_map unique_ptr shared_ptr "
         "FILE Bytef uLong uInt").split()
CONSTS = "true false nullptr NULL EOF stdin stdout stderr".split()


class CppHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        word = lambda ws: r"\b(?:" + "|".join(ws) + r")\b"
        R = QRegularExpression
        self.rules = [
            (R(r"\b[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?[fFuUlL]*\b|\b0[xX][0-9a-fA-F]+\b"), fmt("peach")),
            (R(r"[+\-*/%=<>!&|^~?:]+"), fmt("sky")),
            (R(r"\b[A-Za-z_]\w*(?=\s*\()"), fmt("blue")),
            (R(r"\b[A-Z][A-Z0-9_]{2,}\b"), fmt("peach")),
            (R(word(KEYWORDS)), fmt("mauve")),
            (R(word(TYPES)), fmt("yellow")),
            (R(word(CONSTS)), fmt("peach", bold=True)),
            (R(r"::|->|\."), fmt("teal")),
            (R(r"^\s*#\s*\w+"), fmt("pink")),
            (R(r"(?<=#include)\s*<[^>]*>"), fmt("green")),
            (R(r"\"(\\.|[^\"\\])*\"|'(\\.|[^'\\])*'"), fmt("green")),
            (R(r"\\[nrt0\\'\"]"), fmt("pink")),
            (R(r"//[^\n]*"), fmt("overlay0", italic=True)),
        ]
        self.cstart, self.cend, self.cfmt = R(r"/\*"), R(r"\*/"), fmt("overlay0", italic=True)

    def highlightBlock(self, text):
        for rx, f in self.rules:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), f)
        self.setCurrentBlockState(0)
        start = 0 if self.previousBlockState() == 1 else (m.capturedStart() if (m := self.cstart.match(text)).hasMatch() else -1)
        while start >= 0:
            end = self.cend.match(text, start + (0 if self.previousBlockState() == 1 and start == 0 else 2))
            if end.hasMatch():
                n = end.capturedEnd() - start
                self.setFormat(start, n, self.cfmt)
                nxt = self.cstart.match(text, start + n)
                start = nxt.capturedStart() if nxt.hasMatch() else -1
            else:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self.cfmt)
                start = -1


class LineNumbers(QWidget):
    def __init__(self, ed):
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):
        return QSize(self.ed.margin_width(), 0)

    def paintEvent(self, e):
        self.ed.paint_numbers(e)


class CodeEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setObjectName("editor")
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.nums = LineNumbers(self)
        self.blockCountChanged.connect(lambda _: self.setViewportMargins(self.margin_width(), 0, 0, 0))
        self.updateRequest.connect(self._scroll_nums)
        self.cursorPositionChanged.connect(self._hl_line)
        self.setViewportMargins(self.margin_width(), 0, 0, 0)
        self.highlighter = CppHighlighter(self.document())
        self._hl_line()

    def margin_width(self):
        return 16 + self.fontMetrics().horizontalAdvance("9") * max(3, len(str(self.blockCount())))

    def _scroll_nums(self, rect, dy):
        if dy:
            self.nums.scroll(0, dy)
        else:
            self.nums.update(0, rect.y(), self.nums.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.setViewportMargins(self.margin_width(), 0, 0, 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.nums.setGeometry(QRect(cr.left(), cr.top(), self.margin_width(), cr.height()))

    def paint_numbers(self, event):
        p = QPainter(self.nums)
        p.fillRect(event.rect(), QColor(P["crust"]))
        block = self.firstVisibleBlock()
        n = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = self.textCursor().blockNumber()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                p.setPen(QColor(P["lavender"] if n == cur else P["surface2"]))
                p.drawText(0, top, self.nums.width() - 8, self.fontMetrics().height(), Qt.AlignRight, str(n + 1))
            block = block.next()
            top, bottom, n = bottom, bottom + round(self.blockBoundingRect(block).height()), n + 1

    def _hl_line(self):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(P["surface0"]))
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Tab:
            self.insertPlainText("    ")
        else:
            super().keyPressEvent(e)


# ---------------- background tasks ----------------
class Signals(QObject):
    log = Signal(str)
    done = Signal(object, object)


class Task(QRunnable):
    def __init__(self, fn, sig):
        super().__init__()
        self.fn, self.sig = fn, sig

    def run(self):
        core.log = self.sig.log.emit
        try:
            res, err = self.fn(), None
        except Exception as e:  # noqa: BLE001 - surfaced in the log
            res, err = None, e
        self.sig.done.emit(res, err)


SAMPLE = r'''#include <iostream>
#include <zlib.h>   // devpip install zlib

/* devpip playground: edit, then Build & Run */
int main() {
    const char *msg = "hello hello hello hello devpip!";
    uLong srcLen = 31;
    uLong bound = compressBound(srcLen);
    Bytef out[128];
    if (compress(out, &bound, (const Bytef *)msg, srcLen) == Z_OK)
        std::cout << "zlib " << zlibVersion() << ": " << srcLen << " -> " << bound << " bytes\n";
    return 0;
}
'''


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("devpip · package manager for Dev-C++")
        self.resize(1100, 780)
        self.pool, self.busy_buttons = QThreadPool.globalInstance(), []
        self.sig = Signals()
        self.sig.log.connect(self.log_line)
        self.sig.done.connect(self._task_done)
        self._cb = None

        root = QWidget(); root.setObjectName("root"); self.setCentralWidget(root)
        v = QVBoxLayout(root)
        head = QHBoxLayout()
        t = QLabel("devpip"); t.setObjectName("title")
        sub = QLabel("pip-style packages on top of your Dev-C++"); sub.setObjectName("muted")
        self.chip = QLabel(); self.chip.setObjectName("chip")
        head.addWidget(t); head.addWidget(sub); head.addStretch(); head.addWidget(self.chip)
        v.addLayout(head)

        split = QSplitter(Qt.Vertical)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.build_packages(), "Packages")
        self.tabs.addTab(self.build_playground(), "Playground")
        self.tabs.addTab(self.build_settings(), "Settings")
        self.logw = QPlainTextEdit(); self.logw.setObjectName("log"); self.logw.setReadOnly(True)
        self.logw.setMaximumBlockCount(5000)
        split.addWidget(self.tabs); split.addWidget(self.logw); split.setSizes([560, 180])
        v.addWidget(split)
        self.refresh_toolchain()
        self.refresh_installed()
        self.show_results(core.search(""))

    # ----- pages -----
    def btn(self, text, slot, name=None, busy=True):
        b = QPushButton(text)
        if name:
            b.setObjectName(name)
        b.clicked.connect(slot)
        if busy:
            self.busy_buttons.append(b)
        return b

    def build_packages(self):
        w = QWidget(); h = QHBoxLayout(w)
        left = QVBoxLayout()
        row = QHBoxLayout()
        self.q = QLineEdit(); self.q.setPlaceholderText("search packages (e.g. zlib, sdl, boost)…")
        self.q.returnPressed.connect(self.do_search)
        row.addWidget(self.q); row.addWidget(self.btn("Search", self.do_search))
        self.results = QListWidget(); self.results.itemDoubleClicked.connect(lambda _: self.do_install())
        left.addLayout(row); left.addWidget(self.results)
        left.addWidget(self.btn("Install selected", self.do_install, "primary"))
        right = QVBoxLayout()
        right.addWidget(QLabel("Installed"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Package", "Version", "Mode", "Type"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        right.addWidget(self.table)
        right.addWidget(self.btn("Remove selected", self.do_remove, "danger"))
        right.addWidget(QLabel("Compiler / linker flags"))
        self.flags = QPlainTextEdit(); self.flags.setObjectName("flags"); self.flags.setReadOnly(True)
        self.flags.setMaximumHeight(110)
        right.addWidget(self.flags)
        right.addWidget(self.btn("Copy flags", self.copy_flags, busy=False))
        h.addLayout(left, 1); h.addLayout(right, 1)
        return w

    def build_playground(self):
        w = QWidget(); v = QVBoxLayout(w)
        bar = QHBoxLayout()
        bar.addWidget(self.btn("Build", lambda: self.do_build(False)))
        bar.addWidget(self.btn("Build && Run", lambda: self.do_build(True), "primary"))
        bar.addWidget(self.btn("Reset sample", lambda: self.editor.setPlainText(SAMPLE), busy=False))
        bar.addStretch()
        hint = QLabel("Uses Dev-C++'s own g++ plus your installed packages"); hint.setObjectName("muted")
        bar.addWidget(hint)
        self.editor = CodeEditor(); self.editor.setPlainText(SAMPLE)
        v.addLayout(bar); v.addWidget(self.editor)
        return w

    def build_settings(self):
        w = QWidget(); v = QVBoxLayout(w); v.setAlignment(Qt.AlignTop)
        v.addWidget(QLabel("Dev-C++ folder (contains devcpp.exe)"))
        row = QHBoxLayout()
        self.path = QLineEdit(core.load_config().get("devcpp") or core.detect_devcpp() or "")
        row.addWidget(self.path)
        row.addWidget(self.btn("Browse…", self.browse, busy=False))
        row.addWidget(self.btn("Auto-detect", lambda: self.path.setText(core.detect_devcpp() or ""), busy=False))
        v.addLayout(row)
        v.addWidget(QLabel("Install mode"))
        self.mode = QComboBox()
        self.mode.addItem("Managed folder (~/.devpip, Dev-C++ untouched)", "managed")
        self.mode.addItem("Integrated (copy into Dev-C++'s MinGW, headers just work)", "integrated")
        self.mode.setCurrentIndex(1 if core.load_config().get("mode") == "integrated" else 0)
        v.addWidget(self.mode)
        note = QLabel("Integrated mode may need admin rights (Program Files) and never overwrites files it "
                      "didn't install. You still add the -l flags shown on the Packages tab.")
        note.setObjectName("muted"); note.setWordWrap(True)
        v.addWidget(note)
        row2 = QHBoxLayout()
        row2.addWidget(self.btn("Save", self.save_settings, "primary", busy=False))
        row2.addWidget(self.btn("Open Dev-C++", self.open_devcpp, busy=False))
        row2.addStretch()
        v.addLayout(row2)
        self.info = QLabel(); self.info.setObjectName("muted"); v.addWidget(self.info)
        return w

    # ----- state -----
    def log_line(self, s):
        self.logw.appendPlainText(s)

    def run_task(self, fn, cb=None):
        for b in self.busy_buttons:
            b.setEnabled(False)
        self._cb = cb
        self.pool.start(Task(fn, self.sig))

    def _task_done(self, res, err):
        for b in self.busy_buttons:
            b.setEnabled(True)
        if err:
            self.log_line(f"error: {err}")
        elif self._cb:
            self._cb(res)
        self.refresh_installed()

    def refresh_toolchain(self):
        try:
            tc = core.find_toolchain(self.path.text() if hasattr(self, "path") and self.path.text() else None)
            self.chip.setText(f"Dev-C++ · GCC {tc['version']} · {tc['machine'].split('-')[0]}")
            self.chip.setProperty("bad", not tc["is64"])
            self.info.setText(core.doctor() if False else f"gcc: {tc['gcc']}")
            self.tc = tc
        except Exception as e:  # noqa: BLE001
            self.tc = None
            self.chip.setText("Dev-C++ not found"); self.chip.setProperty("bad", True)
            self.info.setText(str(e))
        self.chip.style().unpolish(self.chip); self.chip.style().polish(self.chip)

    def refresh_installed(self):
        state = core.load_state()
        self.table.setRowCount(len(state))
        for i, (n, e) in enumerate(sorted(state.items())):
            for j, val in enumerate((n, e["version"], e.get("mode", "managed"), "package" if e["explicit"] else "dependency")):
                it = QTableWidgetItem(val)
                if j == 0:
                    it.setForeground(QColor(P["blue"]))
                elif j == 3 and not e["explicit"]:
                    it.setForeground(QColor(P["overlay1"]))
                self.table.setItem(i, j, it)
        try:
            c, l = core.compile_flags(self.tc)
            self.flags.setPlainText(f"Compiler: {' '.join(c) or '(none needed)'}\nLinker:   {' '.join(l) or '(none)'}")
        except Exception:  # noqa: BLE001
            self.flags.setPlainText("")

    def show_results(self, rows):
        self.results.clear()
        for name, ver, cur in rows:
            it = QListWidgetItem(f"{name}   {ver}" + ("   ★ curated" if cur else ""))
            it.setData(Qt.UserRole, name)
            it.setForeground(QColor(P["yellow"] if cur else P["text"]))
            self.results.addItem(it)
        if not rows:
            self.log_line("no packages matched")

    # ----- actions -----
    def do_search(self):
        q = self.q.text()
        self.run_task(lambda: core.search(q), self.show_results)

    def do_install(self):
        it = self.results.currentItem()
        if it:
            name = it.data(Qt.UserRole)
            self.run_task(lambda: core.install([name]))

    def do_remove(self):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        names = [self.table.item(r, 0).text() for r in rows]
        if names:
            self.run_task(lambda: core.remove(names))

    def copy_flags(self):
        QGuiApplication.clipboard().setText(self.flags.toPlainText())
        self.log_line("flags copied to clipboard")

    def do_build(self, run):
        src_dir = core.HOME / "playground"
        src_dir.mkdir(parents=True, exist_ok=True)
        src, exe = src_dir / "main.cpp", src_dir / "main.exe"
        src.write_text(self.editor.toPlainText())

        def job():
            cmd, rc, out = core.build([src], exe)
            core.log(" ".join(cmd))
            if out:
                core.log(out)
            if rc:
                raise core.DevpipError("build failed")
            core.log("build OK")
            if run:
                r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=15, cwd=src_dir,
                                   creationflags=core.NOWIN, env=core.toolchain_env(self.tc))
                core.log("--- output ---\n" + (r.stdout + r.stderr).rstrip() + f"\n--- exit {r.returncode} ---")
        self.run_task(job)

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Dev-C++ folder", self.path.text())
        if d:
            self.path.setText(d)

    def save_settings(self):
        core.save_config({"devcpp": self.path.text().strip(), "mode": self.mode.currentData()})
        self.refresh_toolchain(); self.refresh_installed()
        self.log_line(f"settings saved (mode: {self.mode.currentData()})")

    def open_devcpp(self):
        if self.tc:
            subprocess.Popen([str(self.tc["root"] / "devcpp.exe")])


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(stylesheet())
    w = MainWindow(); w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
