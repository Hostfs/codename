"""
resource_advisor_gui.py  –  PyQt6 기반 시스템 자원 AI 어드바이저
"""
from __future__ import annotations

import sys
import time

import psutil

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QFont, QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QProgressBar, QPushButton, QSlider,
    QComboBox, QTextEdit, QFrame, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QGroupBox, QLineEdit, QSizePolicy, QSplitter,
    QMenuBar, QMenu, QMessageBox, QStatusBar, QTabWidget, QFileDialog,
)

from resource_core import (
    OPENROUTER_API_KEY,
    AVAILABLE_MODELS,
    DEFAULT_ELECTRICITY_RATE_WON_PER_KWH,
    ResourceMonitor,
    snapshot_to_text,
    ask_llm,
    ask_llm_question,
    get_disk_snapshot,
)
from resource_actions import (
    list_running_processes,
    analyze_unnecessary_processes,
    kill_process_by_name,
    scan_storage,
    delete_files,
    list_installed_programs,
    analyze_security_bloatware,
    uninstall_program,
    collect_files_for_malware_scan,
    collect_selected_files_for_malware_scan,
    analyze_malware,
    HAS_SEND2TRASH,
)

# ─────────────────────────────────────────────────────────────
# 색상 팔레트 (Catppuccin Mocha)
# ─────────────────────────────────────────────────────────────
C = {
    "base":     "#1e1e2e",
    "mantle":   "#181825",
    "crust":    "#11111b",
    "surface0": "#313244",
    "surface1": "#45475a",
    "surface2": "#585b70",
    "overlay0": "#6c7086",
    "text":     "#cdd6f4",
    "subtext":  "#a6adc8",
    "blue":     "#89b4fa",
    "lavender": "#b4befe",
    "mauve":    "#cba6f7",
    "pink":     "#f38ba8",
    "red":      "#f87171",
    "peach":    "#fab387",
    "yellow":   "#f9e2af",
    "green":    "#a6e3a1",
    "teal":     "#94e2d5",
    "sky":      "#89dceb",
}

STYLESHEET = f"""
* {{ font-family: "Segoe UI", "맑은 고딕", sans-serif; font-size: 10pt; }}
QMainWindow, QWidget {{ background-color: {C['crust']}; color: {C['text']}; }}
QMenuBar {{ background-color: {C['mantle']}; color: {C['text']}; border-bottom: 1px solid {C['surface0']}; }}
QMenuBar::item:selected {{ background-color: {C['surface0']}; }}
QMenu {{ background-color: {C['base']}; color: {C['text']}; border: 1px solid {C['surface0']}; }}
QMenu::item:selected {{ background-color: {C['surface1']}; }}
QMenu::separator {{ background: {C['surface0']}; height: 1px; margin: 3px 0; }}
QStatusBar {{ background-color: {C['mantle']}; color: {C['subtext']}; border-top: 1px solid {C['surface0']}; }}
QFrame#card {{ background-color: {C['base']}; border: 1px solid {C['surface0']}; border-radius: 10px; }}
QGroupBox {{
    background-color: {C['base']}; border: 1px solid {C['surface0']}; border-radius: 8px;
    margin-top: 14px; padding-top: 6px; font-weight: bold; color: {C['subtext']};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {C['mauve']}; }}
QPushButton {{
    background-color: {C['surface0']}; color: {C['text']}; border: none;
    border-radius: 6px; padding: 7px 14px;
}}
QPushButton:hover {{ background-color: {C['surface1']}; }}
QPushButton:pressed {{ background-color: {C['surface2']}; }}
QPushButton:disabled {{ background-color: {C['surface0']}; color: {C['overlay0']}; }}
QPushButton#analyzeBtn {{
    background-color: #6d28d9; color: white; font-weight: bold; font-size: 11pt;
    padding: 9px; border-radius: 8px;
}}
QPushButton#analyzeBtn:hover {{ background-color: #7c3aed; }}
QPushButton#analyzeBtn:disabled {{ background-color: {C['surface0']}; color: {C['overlay0']}; }}
QPushButton#sendBtn {{
    background-color: {C['blue']}; color: {C['crust']}; font-weight: bold;
    border-radius: 6px; padding: 7px 16px;
}}
QPushButton#sendBtn:hover {{ background-color: {C['lavender']}; }}
QPushButton#sendBtn:disabled {{ background-color: {C['surface0']}; color: {C['overlay0']}; }}
QProgressBar {{
    background-color: {C['surface0']}; border: none; border-radius: 4px;
    height: 10px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ border-radius: 4px; background-color: {C['blue']}; }}
QSlider::groove:horizontal {{
    background: {C['surface0']}; height: 6px; border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {C['lavender']}; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: {C['mauve']}; border-radius: 3px; }}
QComboBox {{
    background-color: {C['surface0']}; color: {C['text']}; border: 1px solid {C['surface1']};
    border-radius: 6px; padding: 5px 8px; min-height: 24px;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {C['surface0']}; color: {C['text']};
    selection-background-color: {C['surface1']}; border: 1px solid {C['surface1']};
    outline: none;
}}
QCheckBox {{ spacing: 6px; color: {C['text']}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1.5px solid {C['surface2']}; background: {C['surface0']};
}}
QCheckBox::indicator:checked {{ background-color: {C['mauve']}; border-color: {C['mauve']}; }}
QTextEdit {{
    background-color: {C['base']}; color: {C['text']}; border: 1px solid {C['surface0']};
    border-radius: 8px; padding: 8px; font-size: 10pt; line-height: 1.4;
}}
QLineEdit {{
    background-color: {C['surface0']}; color: {C['text']}; border: 1px solid {C['surface1']};
    border-radius: 6px; padding: 5px 10px;
}}
QLineEdit:focus {{ border-color: {C['mauve']}; }}
QTableWidget {{
    background-color: {C['base']}; color: {C['text']}; border: none;
    gridline-color: {C['surface0']}; selection-background-color: {C['surface1']};
    outline: none; font-size: 9pt;
}}
QTableWidget::item {{ padding: 4px 6px; border: none; }}
QHeaderView::section {{
    background-color: {C['surface0']}; color: {C['mauve']}; font-weight: bold;
    padding: 5px 6px; border: none; border-bottom: 1px solid {C['surface1']};
}}
QTableWidget::item:selected {{ background-color: {C['surface1']}; color: {C['text']}; }}
QScrollBar:vertical {{
    background: {C['mantle']}; width: 8px; border-radius: 4px;
}}
QScrollBar::handle:vertical {{ background: {C['surface1']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: {C['mantle']}; height: 8px; border-radius: 4px;
}}
QScrollBar::handle:horizontal {{ background: {C['surface1']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollArea {{ border: none; background: transparent; }}
QSplitter::handle {{ background: {C['surface0']}; }}
"""


# ─────────────────────────────────────────────────────────────
# 색상 헬퍼
# ─────────────────────────────────────────────────────────────
def _usage_color(pct: float) -> str:
    if pct <= 50:
        return C["green"]
    if pct <= 80:
        return C["yellow"]
    return C["red"]


def _set_bar_color(bar: QProgressBar, color: str):
    bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}")


def make_card(parent=None) -> QFrame:
    f = QFrame(parent)
    f.setObjectName("card")
    f.setFrameShape(QFrame.Shape.StyledPanel)
    return f


def make_label(text="", color=None, bold=False, size=None) -> QLabel:
    lbl = QLabel(text)
    parts = []
    if color:
        parts.append(f"color: {color};")
    if bold:
        parts.append("font-weight: bold;")
    if size:
        parts.append(f"font-size: {size}pt;")
    if parts:
        lbl.setStyleSheet(" ".join(parts))
    return lbl


def make_sep() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"background: {C['surface0']}; max-height: 1px; border: none; margin: 2px 0;")
    return line


# ─────────────────────────────────────────────────────────────
# GPU 카드
# ─────────────────────────────────────────────────────────────
class GpuCard(QFrame):
    def __init__(self, gpu_index: int, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(200)

        lay = QVBoxLayout(self)
        lay.setSpacing(5)
        lay.setContentsMargins(12, 10, 12, 10)

        hdr = QHBoxLayout()
        self.title_lbl = make_label(f"GPU {gpu_index}", color=C["mauve"], bold=True, size=11)
        self.badge_lbl = make_label("", size=9)
        hdr.addWidget(self.title_lbl)
        hdr.addStretch()
        hdr.addWidget(self.badge_lbl)
        lay.addLayout(hdr)

        self.name_lbl = make_label("", color=C["subtext"], size=9)
        self.name_lbl.setWordWrap(True)
        lay.addWidget(self.name_lbl)
        lay.addWidget(make_sep())

        # 사용률
        r1 = QHBoxLayout()
        r1.addWidget(make_label("사용률", color=C["subtext"], size=9))
        self.util_lbl = make_label("-", bold=True)
        r1.addStretch()
        r1.addWidget(self.util_lbl)
        lay.addLayout(r1)
        self.util_bar = QProgressBar()
        self.util_bar.setRange(0, 100)
        self.util_bar.setFixedHeight(8)
        self.util_bar.setTextVisible(False)
        lay.addWidget(self.util_bar)

        # VRAM
        r2 = QHBoxLayout()
        r2.addWidget(make_label("VRAM", color=C["subtext"], size=9))
        self.vram_lbl = make_label("-", bold=True, size=9)
        r2.addStretch()
        r2.addWidget(self.vram_lbl)
        lay.addLayout(r2)
        self.vram_bar = QProgressBar()
        self.vram_bar.setRange(0, 100)
        self.vram_bar.setFixedHeight(8)
        self.vram_bar.setTextVisible(False)
        lay.addWidget(self.vram_bar)

    def update_data(self, g: dict):
        self.title_lbl.setText(f"GPU {g.get('index', '?')}")
        name = g.get("name", "Unknown GPU")
        static_only = g.get("static_only", True)
        util = g.get("util_percent", 0.0)
        mem_used = g.get("mem_used_mb", 0.0)
        mem_total = g.get("mem_total_mb", 0.0)

        self.name_lbl.setText(name)

        if static_only:
            self.badge_lbl.setText("하드웨어 감지")
            self.badge_lbl.setStyleSheet(f"color: {C['pink']}; font-size: 9pt;")
            self.util_lbl.setText("N/A")
            self.util_lbl.setStyleSheet(f"color: {C['overlay0']}; font-weight: bold;")
            self.util_bar.setValue(0)
            _set_bar_color(self.util_bar, C["surface1"])
        else:
            self.badge_lbl.setText("● LIVE")
            self.badge_lbl.setStyleSheet(f"color: {C['green']}; font-size: 9pt;")
            c = _usage_color(util)
            self.util_lbl.setText(f"{util:.0f}%")
            self.util_lbl.setStyleSheet(f"color: {c}; font-weight: bold;")
            self.util_bar.setValue(int(min(util, 100)))
            _set_bar_color(self.util_bar, c)

        if mem_total > 0:
            vp = (mem_used / mem_total * 100) if not static_only else 0.0
            self.vram_lbl.setText(
                f"{mem_used:.0f} / {mem_total:.0f} MB" if not static_only else f"{mem_total:.0f} MB"
            )
            self.vram_bar.setValue(int(min(vp, 100)))
            _set_bar_color(self.vram_bar, _usage_color(vp) if not static_only else C["surface1"])
        else:
            self.vram_lbl.setText("N/A")
            self.vram_bar.setValue(0)


# ─────────────────────────────────────────────────────────────
# 백그라운드 워커
# ─────────────────────────────────────────────────────────────
class LLMWorker(QObject):
    result = pyqtSignal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self._fn = fn
        self._args = args

    def run(self):
        try:
            res = self._fn(*self._args)
        except Exception as e:
            res = f"오류 발생:\n{e}"
        self.result.emit(res)


class GenericWorker(QObject):
    """임의의 결과(list/dict 등)를 돌려주는 백그라운드 작업 워커.

    work_fn()이 예외를 던지면 ok=False, error에 메시지를 담아 emit한다.
    with_progress=True면 work_fn(progress_cb=...)로 호출되며, work_fn은 작업
    중간에 progress_cb(메시지: str)를 호출해 진행률/예상 잔여 시간을 알릴 수
    있다(시그널이라 작업 스레드 → GUI 스레드로 안전하게 전달된다).
    """
    done = pyqtSignal(bool, object, str)
    progress = pyqtSignal(str)

    def __init__(self, work_fn, with_progress=False):
        super().__init__()
        self._work_fn = work_fn
        self._with_progress = with_progress

    def run(self):
        try:
            if self._with_progress:
                value = self._work_fn(progress_cb=self.progress.emit)
            else:
                value = self._work_fn()
            self.done.emit(True, value, "")
        except Exception as e:
            self.done.emit(False, None, str(e))


SEVERITY_COLOR = {"high": "pink", "medium": "yellow", "low": "subtext"}
RECO_COLOR = {"uninstall": "pink", "disable": "yellow", "keep": "green"}
RISK_COLOR = {"위험": "pink", "주의": "yellow", "정상": "green"}


class SelectableCard(QFrame):
    """체크박스 + 제목/배지 + 부제목 + 본문으로 구성된 결과 카드 (프로세스/프로그램/파일 공용)."""

    def __init__(self, title, badge_text="", badge_color_key="subtext",
                 subtitle="", body="", checked=False, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        top = QHBoxLayout()
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        top.addWidget(self.checkbox)
        top.addWidget(make_label(title, bold=True, size=11))
        top.addStretch()
        if badge_text:
            top.addWidget(make_label(badge_text, color=C.get(badge_color_key, C["subtext"]), bold=True, size=9))
        lay.addLayout(top)

        if subtitle:
            sub_lbl = make_label(subtitle, color=C["overlay0"], size=9)
            sub_lbl.setWordWrap(True)
            lay.addWidget(sub_lbl)

        if body:
            body_lbl = make_label(body, color=C["subtext"], size=9)
            body_lbl.setWordWrap(True)
            lay.addWidget(body_lbl)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()


class FeatureTabBase(QScrollArea):
    """AI 분석 → 체크 가능한 카드 목록 → 일괄 처리 패턴을 공유하는 탭의 베이스 클래스."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._busy = False
        self._cards: list[tuple[QCheckBox, dict]] = []
        self._threads = []  # QThread 참조 유지(GC 방지)

        root = QWidget()
        root.setStyleSheet(f"background-color: {C['crust']};")
        self.root_lay = QVBoxLayout(root)
        self.root_lay.setSpacing(10)
        self.root_lay.setContentsMargins(14, 14, 14, 14)

        header = make_card()
        hl = QVBoxLayout(header)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.addWidget(make_label(self.TITLE, bold=True, size=14, color=C["mauve"]))
        desc_lbl = make_label(self.DESCRIPTION, color=C["subtext"], size=9)
        desc_lbl.setWordWrap(True)
        hl.addWidget(desc_lbl)
        self.root_lay.addWidget(header)

        self.toolbar = QHBoxLayout()
        self.root_lay.addLayout(self.toolbar)

        self.status_lbl = make_label("", color=C["overlay0"], size=9)
        self.status_lbl.setWordWrap(True)
        self.root_lay.addWidget(self.status_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.root_lay.addWidget(self.progress)

        self.results_lay = QVBoxLayout()
        self.results_lay.setSpacing(6)
        self.root_lay.addLayout(self.results_lay)
        self.root_lay.addStretch()

        self.setWidget(root)
        self._show_placeholder(self.PLACEHOLDER)

    # ── 공용 유틸 ──
    def _clear_results(self):
        while self.results_lay.count():
            item = self.results_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards = []

    def _show_placeholder(self, text):
        self._clear_results()
        lbl = make_label(text, color=C["overlay0"])
        self.results_lay.addWidget(lbl)

    def _add_banner(self, text, color_key="green"):
        """결과 목록 위/대신 눈에 잘 띄는 큰 배너를 붙인다(예: 악성파일 없음/발견됨)."""
        banner = QFrame()
        banner.setObjectName("card")
        banner.setStyleSheet(
            f"#card {{ background-color: {C['surface0']}; border: 2px solid {C[color_key]}; "
            f"border-radius: 8px; }}"
        )
        lay = QVBoxLayout(banner)
        lay.setContentsMargins(16, 14, 16, 14)
        lbl = make_label(text, bold=True, size=13, color=C[color_key])
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        self.results_lay.addWidget(banner)

    def _add_card(self, item: dict, title, badge_text, badge_color_key, subtitle, body, checked):
        card = SelectableCard(title, badge_text, badge_color_key, subtitle, body, checked)
        self.results_lay.addWidget(card)
        self._cards.append((card.checkbox, item))

    def _checked_items(self):
        return [item for chk, item in self._cards if chk.isChecked()]

    def run_async(self, work_fn, done_fn, busy_text="처리 중...", on_progress=None):
        """work_fn을 백그라운드 스레드에서 실행한다.

        on_progress가 주어지면 work_fn은 progress_cb 키워드 인자를 받는 형태여야
        한다(work_fn(progress_cb=...)로 호출됨). work_fn 안에서 progress_cb(메시지)를
        호출하면 on_progress(메시지)가 GUI 스레드에서 안전하게 실행된다.
        """
        if self._busy:
            return
        self._busy = True
        self.status_lbl.setText(busy_text)
        self.status_lbl.setStyleSheet(f"color: {C['green']}; font-size: 9pt;")
        self.progress.show()

        t = QThread(self)
        w = GenericWorker(work_fn, with_progress=on_progress is not None)
        w.moveToThread(t)
        t.started.connect(w.run)
        if on_progress:
            w.progress.connect(on_progress)

        def finish(ok, value, err):
            self._busy = False
            self.progress.hide()
            if not ok:
                self.status_lbl.setText(f"오류: {err}")
                self.status_lbl.setStyleSheet(f"color: {C['pink']}; font-size: 9pt;")
                return
            self.status_lbl.setText("")
            done_fn(value)

        w.done.connect(finish)
        w.done.connect(t.quit)
        t.finished.connect(t.deleteLater)
        w.done.connect(w.deleteLater)
        pair = (t, w)
        self._threads.append(pair)
        t.finished.connect(lambda: self._threads.remove(pair) if pair in self._threads else None)
        t.start()


# ─────────────────────────────────────────────────────────────
# 프로세스 테이블
# ─────────────────────────────────────────────────────────────
class ProcessTable(QGroupBox):
    def __init__(self, title: str, mode: str = "cpu", parent=None):
        super().__init__(title, parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 14, 4, 4)
        lay.setSpacing(0)

        if mode == "gpu":
            cols = [("이름", 130), ("PID", 55), ("GPU %", 70)]
        else:
            cols = [("이름", 120), ("PID", 50), ("CPU %", 60), ("MEM %", 60)]

        self._tbl = QTableWidget(0, len(cols))
        self._tbl.setHorizontalHeaderLabels([c[0] for c in cols])
        self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.verticalHeader().setVisible(False)
        self._tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._tbl.setShowGrid(False)
        for i, (_, w) in enumerate(cols):
            self._tbl.setColumnWidth(i, w)
        lay.addWidget(self._tbl)

    def fill(self, rows: list, value_fn):
        self._tbl.setRowCount(len(rows))
        for ri, row in enumerate(rows):
            for ci, val in enumerate(value_fn(row)):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self._tbl.setItem(ri, ci, item)
            self._tbl.setRowHeight(ri, 24)


# ─────────────────────────────────────────────────────────────
# ⚙ 프로세스 최적화 탭
# ─────────────────────────────────────────────────────────────
class ProcessOptimizationTab(FeatureTabBase):
    TITLE = "⚙ 프로세스 최적화"
    DESCRIPTION = (
        "실행 중인 프로세스를 AI에게 보내 불필요·낭비성 프로세스를 판단합니다. "
        "체크 후 종료할 수 있으며, OS 핵심·본 앱 프로세스는 안전을 위해 종료 대상에서 제외됩니다."
    )
    PLACEHOLDER = "‘AI로 분석’을 눌러 시작하세요."

    def __init__(self, get_model, get_temperature, parent=None):
        super().__init__(parent)
        self._get_model = get_model
        self._get_temperature = get_temperature

        analyze_btn = QPushButton("🔍  AI로 분석")
        analyze_btn.setObjectName("analyzeBtn")
        analyze_btn.clicked.connect(self.analyze)
        kill_btn = QPushButton("🛑  선택 종료")
        kill_btn.clicked.connect(self.kill_selected)
        self.toolbar.addWidget(analyze_btn)
        self.toolbar.addWidget(kill_btn)
        self.toolbar.addStretch()

    def analyze(self):
        model, temp = self._get_model(), self._get_temperature()

        def work():
            procs = list_running_processes()
            items, err = analyze_unnecessary_processes(procs, model, temp)
            if err:
                raise RuntimeError(err)
            return items

        self.run_async(work, self._render, "AI가 프로세스를 분석 중입니다...")

    def _render(self, items):
        self._clear_results()
        if not items:
            self._show_placeholder("종료를 권장할 만한 프로세스를 찾지 못했습니다.")
            return
        for it in items:
            sev = it["severity"]
            pid_txt = f"PID: {', '.join(str(p) for p in it['pids'])}" if it["pids"] else "실행 중 아님"
            self._add_card(
                it, it["name"], f"● {sev.upper()}", SEVERITY_COLOR.get(sev, "subtext"),
                pid_txt, it["reason"],
                checked=bool(it["safe_to_kill"] and it["pids"] and sev in ("high", "medium")),
            )

    def kill_selected(self):
        targets = [it for it in self._checked_items() if it["pids"]]
        if not targets:
            QMessageBox.information(self, "프로세스 종료", "선택된(실행 중인) 프로세스가 없습니다.")
            return
        names = "\n".join(f"• {t['name']}" for t in targets)
        if QMessageBox.question(
            self, "프로세스 종료 확인", f"다음 프로세스를 종료하시겠습니까?\n\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return

        killed = failed = 0
        skipped = []
        for t in targets:
            r = kill_process_by_name(t["name"])
            killed += len(r["killed"])
            failed += len(r["failed"])
            if r["skipped"]:
                skipped.append(t["name"])

        msg = f"{killed}개 프로세스를 종료했습니다."
        if failed:
            msg += f"\n{failed}개는 권한 부족 등으로 종료하지 못했습니다 (관리자 권한 필요할 수 있음)."
        if skipped:
            msg += f"\n보호된 프로세스라 제외됨: {', '.join(skipped)}"
        QMessageBox.information(self, "프로세스 종료 완료", msg)
        self.analyze()


# ─────────────────────────────────────────────────────────────
# 💾 저장공간 분석 탭
# ─────────────────────────────────────────────────────────────
class StorageTab(FeatureTabBase):
    TITLE = "💾 저장공간 분석"
    DESCRIPTION = (
        "드라이브 사용량, Temp 폴더, 대용량/오래된 파일을 분석합니다. "
        "Temp는 일괄 비우기, 대용량·오래된 파일은 선택 삭제할 수 있습니다."
    )
    PLACEHOLDER = "‘스캔’을 눌러 저장공간을 분석하세요."

    def __init__(self, parent=None):
        super().__init__(parent)
        self._temp_files = []

        scan_btn = QPushButton("🔍  스캔")
        scan_btn.setObjectName("analyzeBtn")
        scan_btn.clicked.connect(self.scan)
        temp_btn = QPushButton("🧹  Temp 비우기")
        temp_btn.clicked.connect(self.clear_temp)
        del_btn = QPushButton("🗑  선택 삭제")
        del_btn.clicked.connect(self.delete_selected)
        self.toolbar.addWidget(scan_btn)
        self.toolbar.addWidget(temp_btn)
        self.toolbar.addWidget(del_btn)
        self.toolbar.addStretch()

    def scan(self):
        def work(progress_cb=None):
            disks = get_disk_snapshot()
            result = scan_storage(progress_cb=progress_cb)
            result["disks"] = disks
            return result

        self.run_async(
            work, self._render, "저장공간을 스캔 중입니다...",
            on_progress=lambda msg: self.status_lbl.setText(msg),
        )

    def _render(self, data):
        self._clear_results()
        self._temp_files = data["temp"]["files"]

        drive_card = make_card()
        dl = QVBoxLayout(drive_card)
        dl.setContentsMargins(12, 10, 12, 10)
        dl.addWidget(make_label("드라이브 사용량", bold=True, color=C["blue"], size=11))
        for d in data["disks"]:
            dl.addWidget(make_label(
                f"{d['mount']}  {d['percent']:.0f}%  ({d['used_gb']:.1f} / {d['total_gb']:.1f} GB)", size=9
            ))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setFixedHeight(8)
            bar.setTextVisible(False)
            bar.setValue(int(min(d["percent"], 100)))
            _set_bar_color(bar, _usage_color(d["percent"]))
            dl.addWidget(bar)
        self.results_lay.addWidget(drive_card)

        temp = data["temp"]
        temp_card = make_card()
        tl = QVBoxLayout(temp_card)
        tl.setContentsMargins(12, 10, 12, 10)
        tl.addWidget(make_label(f"🧹 Temp 폴더: {temp['count']}개 파일 · 총 {temp['total_h']}",
                                bold=True, color=C["yellow"], size=11))
        dirs_lbl = make_label("대상 경로: " + "  |  ".join(temp["dirs"]), color=C["overlay0"], size=8)
        dirs_lbl.setWordWrap(True)
        tl.addWidget(dirs_lbl)
        self.results_lay.addWidget(temp_card)

        self.results_lay.addWidget(make_label("📦 대용량 파일 (100MB+)", bold=True, color=C["mauve"], size=12))
        if data["large"]:
            for f in data["large"]:
                self._add_card(f, f["path"].split("\\")[-1], f["size_h"], "yellow", f["path"], "", checked=False)
        else:
            self.results_lay.addWidget(make_label("대용량 파일이 없습니다.", color=C["overlay0"]))

        self.results_lay.addWidget(make_label("🕒 오래된 파일 (180일+ / 10MB+)", bold=True, color=C["mauve"], size=12))
        if data["old"]:
            for f in data["old"]:
                self._add_card(
                    f, f["path"].split("\\")[-1], f"{f['size_h']} · {f.get('age_days', '?')}일 전",
                    "subtext", f["path"], "", checked=False
                )
        else:
            self.results_lay.addWidget(make_label("오래된 파일이 없습니다.", color=C["overlay0"]))

    def clear_temp(self):
        if not self._temp_files:
            QMessageBox.information(self, "Temp 비우기", "먼저 ‘스캔’을 실행하세요.")
            return
        count = len(self._temp_files)
        if QMessageBox.question(
            self, "Temp 비우기 확인",
            f"Temp 폴더의 {count}개 파일을 삭제하시겠습니까?\n(사용 중인 일부 파일은 건너뜁니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        res = delete_files([f["path"] for f in self._temp_files])
        QMessageBox.information(
            self, "Temp 비우기 완료",
            f"{len(res['deleted'])}개 삭제, {res['freed_h']} 확보\n실패(사용 중 등): {len(res['failed'])}개"
        )
        self.scan()

    def delete_selected(self):
        targets = self._checked_items()
        # 드라이브/Temp 카드는 체크박스가 없으므로 path 키가 있는 항목만 대상
        targets = [t for t in targets if "path" in t]
        if not targets:
            QMessageBox.information(self, "파일 삭제", "선택된 파일이 없습니다.")
            return
        sample = "\n".join(f"• {t['path']}" for t in targets[:10])
        more = f"\n... 외 {len(targets) - 10}개" if len(targets) > 10 else ""
        dest = "휴지통으로 이동" if HAS_SEND2TRASH else "영구 삭제"
        if QMessageBox.question(
            self, "파일 삭제 확인", f"{len(targets)}개 파일을 {dest}하시겠습니까?\n\n{sample}{more}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        res = delete_files([t["path"] for t in targets])
        QMessageBox.information(
            self, "삭제 완료", f"{len(res['deleted'])}개 삭제, {res['freed_h']} 확보\n실패: {len(res['failed'])}개"
        )
        self.scan()


# ─────────────────────────────────────────────────────────────
# 🛡 보안 프로그램 탭 (구라제거기)
# ─────────────────────────────────────────────────────────────
class SecurityTab(FeatureTabBase):
    TITLE = "🛡 불필요한 보안/최적화 프로그램 (구라제거기)"
    DESCRIPTION = (
        "설치된 프로그램을 AI에게 보내 효과가 과장된 최적화·클리너, 중복 백신, PUP 등을 가려냅니다. "
        "판단 근거와 함께 표시되며, 선택해 제거할 수 있습니다."
    )
    PLACEHOLDER = "‘AI로 분석’을 눌러 시작하세요. (설치 목록 조회에 수 초 걸릴 수 있습니다)"

    def __init__(self, get_model, get_temperature, parent=None):
        super().__init__(parent)
        self._get_model = get_model
        self._get_temperature = get_temperature

        analyze_btn = QPushButton("🔍  AI로 분석")
        analyze_btn.setObjectName("analyzeBtn")
        analyze_btn.clicked.connect(self.analyze)
        uninstall_btn = QPushButton("🧯  선택 제거")
        uninstall_btn.clicked.connect(self.uninstall_selected)
        self.toolbar.addWidget(analyze_btn)
        self.toolbar.addWidget(uninstall_btn)
        self.toolbar.addStretch()

    def analyze(self):
        model, temp = self._get_model(), self._get_temperature()

        def work():
            programs = list_installed_programs()
            running = {p.info["name"] for p in psutil.process_iter(["name"]) if p.info.get("name")}
            items, err = analyze_security_bloatware(programs, running, model, temp)
            if err:
                raise RuntimeError(err)
            return items

        self.run_async(work, self._render, "AI가 설치 프로그램을 분석 중입니다...")

    def _render(self, items):
        self._clear_results()
        flagged = [it for it in items if it["recommendation"] != "keep"]
        if not flagged:
            self._show_placeholder("제거를 권장할 만한 프로그램을 찾지 못했습니다.")
            return
        for it in flagged:
            reco = it["recommendation"]
            badge = {"uninstall": "제거 권장", "disable": "비활성 권장"}.get(reco, reco)
            body = "현재 실행 중" if it["running"] else ""
            if not it["uninstall_string"]:
                body = (body + "  ·  제거 명령 없음(수동 제거 필요)").strip()
            self._add_card(
                it, it["name"], f"● {badge}", RECO_COLOR.get(reco, "yellow"),
                it["reason"], body, checked=(reco == "uninstall" and bool(it["uninstall_string"]))
            )

    def uninstall_selected(self):
        targets = self._checked_items()
        if not targets:
            QMessageBox.information(self, "프로그램 제거", "선택된 프로그램이 없습니다.")
            return
        removable = [t for t in targets if t["uninstall_string"]]
        if not removable:
            QMessageBox.warning(self, "프로그램 제거",
                                "선택한 항목에 제거 명령이 없어 자동 제거할 수 없습니다. 수동으로 제거하세요.")
            return
        names = "\n".join(f"• {t['name']}" for t in removable)
        if QMessageBox.question(
            self, "프로그램 제거 확인",
            f"다음 프로그램의 제거 관리자를 실행합니다.\n각 제거 창의 안내를 따라야 합니다.\n\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        ok, fails = 0, []
        for t in removable:
            success, _msg = uninstall_program(t["uninstall_string"])
            if success:
                ok += 1
            else:
                fails.append(t["name"])
        msg = f"{ok}개 프로그램의 제거 관리자를 실행했습니다."
        if fails:
            msg += f"\n실행 실패: {', '.join(fails)}"
        QMessageBox.information(self, "프로그램 제거", msg)


# ─────────────────────────────────────────────────────────────
# 🦠 악성파일 분석 탭
# ─────────────────────────────────────────────────────────────
class MalwareTab(FeatureTabBase):
    TITLE = "🦠 악성파일 분석"
    DESCRIPTION = (
        "Downloads · Temp · AppData · 바탕화면의 실행/스크립트 파일을 수집하고 코드 서명 상태를 확인해 "
        "AI가 위험도(위험/주의)를 판단합니다. 정밀 백신이 아닌 휴리스틱 판단이므로 삭제 전 확인하세요."
    )
    PLACEHOLDER = "‘AI로 스캔’을 눌러 시작하세요. (파일 수집·서명 확인에 시간이 걸릴 수 있습니다)"

    def __init__(self, get_model, parent=None):
        super().__init__(parent)
        self._get_model = get_model

        scan_btn = QPushButton("🔍  AI로 스캔")
        scan_btn.setObjectName("analyzeBtn")
        scan_btn.clicked.connect(self.scan)
        pick_btn = QPushButton("📁  파일 선택해서 분석")
        pick_btn.clicked.connect(self.scan_selected_files)
        del_btn = QPushButton("🗑  선택 삭제")
        del_btn.clicked.connect(self.delete_selected)
        self.toolbar.addWidget(scan_btn)
        self.toolbar.addWidget(pick_btn)
        self.toolbar.addWidget(del_btn)
        self.toolbar.addStretch()

    def scan(self):
        model = self._get_model()

        def work():
            files = collect_files_for_malware_scan()
            if not files:
                return []
            items, err = analyze_malware(files, model)
            if err:
                raise RuntimeError(err)
            return items

        self.run_async(work, self._render, "파일 수집 및 AI 위험도 분석 중입니다...")

    def scan_selected_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "분석할 파일 선택")
        if not paths:
            return
        model = self._get_model()

        def work():
            files = collect_selected_files_for_malware_scan(paths)
            if not files:
                return []
            items, err = analyze_malware(files, model)
            if err:
                raise RuntimeError(err)
            return items

        self.run_async(work, self._render, "선택한 파일을 AI로 분석 중입니다...")

    def _render(self, items):
        self._clear_results()
        if not items:
            self._add_banner("✅ 바이러스/악성코드로 의심되는 파일을 찾지 못했습니다.", "green")
            return

        danger = sum(1 for it in items if it["risk"] == "위험")
        caution = len(items) - danger
        if danger:
            self._add_banner(
                f"🚨 {danger}개 파일에서 바이러스/악성코드가 의심됩니다. (주의 {caution}개 추가 발견)",
                "pink",
            )
        else:
            self._add_banner(f"⚠ {caution}개 파일이 주의 대상으로 분류되었습니다.", "yellow")

        for it in items:
            risk = it["risk"]
            sub = f"{it['threat_type']}  ·  {it['size_h']}  ·  서명: {it['signature']}"
            body = f"{it['reason']}\n{it['path']}"
            self._add_card(
                it, it["name"], f"● {risk}", RISK_COLOR.get(risk, "yellow"),
                sub, body, checked=(risk == "위험")
            )

    def delete_selected(self):
        targets = self._checked_items()
        if not targets:
            QMessageBox.information(self, "파일 삭제", "선택된 파일이 없습니다.")
            return
        sample = "\n".join(f"• [{t['risk']}] {t['path']}" for t in targets[:10])
        more = f"\n... 외 {len(targets) - 10}개" if len(targets) > 10 else ""
        dest = "휴지통으로 이동" if HAS_SEND2TRASH else "영구 삭제"
        if QMessageBox.question(
            self, "악성파일 삭제 확인", f"{len(targets)}개 파일을 {dest}하시겠습니까?\n\n{sample}{more}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) != QMessageBox.StandardButton.Yes:
            return
        res = delete_files([t["path"] for t in targets])
        QMessageBox.information(
            self, "삭제 완료", f"{len(res['deleted'])}개 삭제, {res['freed_h']} 확보\n실패: {len(res['failed'])}개"
        )
        self.scan()


# ─────────────────────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────────────────────
class Sidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)
        self.setStyleSheet(f"background-color: {C['mantle']}; border-right: 1px solid {C['surface0']};")

        outer = QVBoxLayout(self)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        inner = QWidget()
        inner.setStyleSheet(f"background-color: {C['mantle']};")
        lay = QVBoxLayout(inner)
        lay.setSpacing(8)
        lay.setContentsMargins(14, 14, 14, 14)

        # ── 타이틀
        lay.addWidget(make_label("⚙  설정", color=C["mauve"], bold=True, size=14))
        lay.addWidget(make_sep())

        # ── 모델
        lay.addWidget(make_label("사용 모델", color=C["subtext"], size=9))
        self.model_combo = QComboBox()
        self.model_combo.addItems(AVAILABLE_MODELS)
        self.model_combo.setStyleSheet(f"""
            QComboBox {{ background-color: {C['surface0']}; color: {C['text']};
                border: 1px solid {C['surface1']}; border-radius: 6px; padding: 5px 8px; }}
            QComboBox QAbstractItemView {{ background-color: {C['surface0']}; color: {C['text']};
                selection-background-color: {C['surface1']}; }}
        """)
        lay.addWidget(self.model_combo)

        # ── Temperature
        lay.addWidget(make_label("Temperature", color=C["subtext"], size=9))
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(0, 100)
        self.temp_slider.setValue(30)
        self.temp_val_lbl = make_label("0.30", color=C["subtext"], size=9)
        self.temp_slider.valueChanged.connect(lambda v: self.temp_val_lbl.setText(f"{v/100:.2f}"))
        tr = QHBoxLayout()
        tr.addWidget(self.temp_slider)
        tr.addWidget(self.temp_val_lbl)
        lay.addLayout(tr)
        lay.addWidget(make_sep())

        # ── 새로고침 주기
        lay.addWidget(make_label("새로고침 주기 (초)", color=C["subtext"], size=9))
        self.ref_slider = QSlider(Qt.Orientation.Horizontal)
        self.ref_slider.setRange(1, 30)
        self.ref_slider.setValue(2)
        self.ref_val_lbl = make_label("2초", color=C["subtext"], size=9)
        self.ref_slider.valueChanged.connect(lambda v: self.ref_val_lbl.setText(f"{v}초"))
        rr = QHBoxLayout()
        rr.addWidget(self.ref_slider)
        rr.addWidget(self.ref_val_lbl)
        lay.addLayout(rr)
        lay.addWidget(make_sep())

        # ── AI 자동 분석
        self.auto_chk = QCheckBox("AI 자동 분석 활성화")
        self.auto_chk.setStyleSheet(f"color: {C['text']};")
        lay.addWidget(self.auto_chk)

        lay.addWidget(make_label("AI 분석 주기 (초)", color=C["subtext"], size=9))
        self.ai_slider = QSlider(Qt.Orientation.Horizontal)
        self.ai_slider.setRange(30, 600)
        self.ai_slider.setValue(60)
        self.ai_val_lbl = make_label("60초", color=C["subtext"], size=9)
        self.ai_slider.valueChanged.connect(lambda v: self.ai_val_lbl.setText(f"{v}초"))
        ar = QHBoxLayout()
        ar.addWidget(self.ai_slider)
        ar.addWidget(self.ai_val_lbl)
        lay.addLayout(ar)
        lay.addWidget(make_sep())

        # ── 전기요금
        lay.addWidget(make_label("전기요금 (원/kWh)", color=C["subtext"], size=9))
        self.rate_slider = QSlider(Qt.Orientation.Horizontal)
        self.rate_slider.setRange(100, 400)
        self.rate_slider.setValue(int(DEFAULT_ELECTRICITY_RATE_WON_PER_KWH))
        self.rate_val_lbl = make_label(f"{int(DEFAULT_ELECTRICITY_RATE_WON_PER_KWH)}원/kWh", color=C["subtext"], size=9)
        self.rate_slider.valueChanged.connect(lambda v: self.rate_val_lbl.setText(f"{v}원/kWh"))
        er = QHBoxLayout()
        er.addWidget(self.rate_slider)
        er.addWidget(self.rate_val_lbl)
        lay.addLayout(er)
        lay.addWidget(make_sep())

        # ── 분석 버튼
        self.analyze_btn = QPushButton("🔍  지금 분석하기")
        self.analyze_btn.setObjectName("analyzeBtn")
        self.analyze_btn.setMinimumHeight(40)
        lay.addWidget(self.analyze_btn)

        self.status_lbl = make_label("", color=C["subtext"], size=9)
        self.status_lbl.setWordWrap(True)
        lay.addWidget(self.status_lbl)

        if not OPENROUTER_API_KEY:
            w = make_label("⚠ .env에 OPENROUTER_API_KEY 없음", color=C["pink"], size=9)
            w.setWordWrap(True)
            lay.addWidget(w)

        lay.addStretch()

        note = make_label(
            "OpenRouter API 사용 · 분석마다 비용 발생\n"
            "전력 측정: Intel CPU(RAPL)·NVIDIA GPU·배터리는 자동 측정\nLHM 관리자 실행 시 더 상세히 측정",
            color=C["surface2"], size=8
        )
        note.setWordWrap(True)
        lay.addWidget(note)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    @property
    def model(self) -> str:
        return self.model_combo.currentText()

    @property
    def temperature(self) -> float:
        return self.temp_slider.value() / 100.0

    @property
    def refresh_sec(self) -> int:
        return self.ref_slider.value()

    @property
    def auto_analyze(self) -> bool:
        return self.auto_chk.isChecked()

    @property
    def ai_interval_sec(self) -> int:
        return self.ai_slider.value()

    @property
    def electricity_rate(self) -> float:
        return float(self.rate_slider.value())


# ─────────────────────────────────────────────────────────────
# 대시보드 (메인 패널)
# ─────────────────────────────────────────────────────────────
class Dashboard(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        root_w = QWidget()
        root_w.setStyleSheet(f"background-color: {C['crust']};")
        lay = QVBoxLayout(root_w)
        lay.setSpacing(10)
        lay.setContentsMargins(14, 14, 14, 14)

        # ── 헤더 카드
        hdr = make_card()
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(14, 10, 14, 10)
        hl.addWidget(make_label("🖥  시스템 자원 AI 어드바이저", bold=True, size=15))
        hl.addStretch()
        self.ts_lbl = make_label("마지막 갱신: -", color=C["overlay0"], size=9)
        hl.addWidget(self.ts_lbl)
        lay.addWidget(hdr)

        # ── CPU / RAM 카드
        cr_card = make_card()
        cr = QGridLayout(cr_card)
        cr.setContentsMargins(14, 12, 14, 12)
        cr.setHorizontalSpacing(24)
        cr.setVerticalSpacing(4)

        cr.addWidget(make_label("🖥  CPU", color=C["blue"], bold=True, size=12), 0, 0)
        self.cpu_pct_lbl = make_label("-", bold=True, size=12)
        cr.addWidget(self.cpu_pct_lbl, 0, 1, Qt.AlignmentFlag.AlignRight)
        self.cpu_bar = QProgressBar()
        self.cpu_bar.setRange(0, 100); self.cpu_bar.setFixedHeight(10); self.cpu_bar.setTextVisible(False)
        cr.addWidget(self.cpu_bar, 1, 0, 1, 2)

        cr.addWidget(make_label("📊  RAM", color=C["sky"], bold=True, size=12), 0, 2)
        self.ram_pct_lbl = make_label("-", bold=True, size=12)
        cr.addWidget(self.ram_pct_lbl, 0, 3, Qt.AlignmentFlag.AlignRight)
        self.ram_bar = QProgressBar()
        self.ram_bar.setRange(0, 100); self.ram_bar.setFixedHeight(10); self.ram_bar.setTextVisible(False)
        cr.addWidget(self.ram_bar, 1, 2, 1, 2)
        self.ram_detail_lbl = make_label("- / - GB", color=C["overlay0"], size=9)
        cr.addWidget(self.ram_detail_lbl, 2, 2, 1, 2)
        cr.setColumnStretch(0, 1); cr.setColumnStretch(2, 1)
        lay.addWidget(cr_card)

        # ── GPU 섹션
        lay.addWidget(make_label("GPU", color=C["mauve"], bold=True, size=12))
        self._gpu_row_w = QWidget()
        self._gpu_row_w.setStyleSheet("background: transparent;")
        self._gpu_row = QHBoxLayout(self._gpu_row_w)
        self._gpu_row.setSpacing(8)
        self._gpu_row.setContentsMargins(0, 0, 0, 0)
        self._gpu_cards: dict[str, GpuCard] = {}  # GPU 이름 → 카드(이름이 안정적인 고유 키)
        lay.addWidget(self._gpu_row_w)

        # ── 디스크 / 전력
        dp = QHBoxLayout()
        dp.setSpacing(8)

        self._disk_grp = QGroupBox("💾  디스크")
        self._disk_lay = QVBoxLayout(self._disk_grp)
        self._disk_lay.setSpacing(3)
        self._disk_lay.setContentsMargins(10, 14, 10, 10)
        self._disk_ws: list[dict] = []

        pw_grp = QGroupBox("⚡  전력")
        pl = QVBoxLayout(pw_grp)
        pl.setContentsMargins(10, 14, 10, 10)
        pl.setSpacing(4)
        self.pw_now_lbl = make_label("소비 전력: N/A", color=C["subtext"])
        self.pw_cum_lbl = make_label("누적 사용량/비용: -", color=C["subtext"])
        self.pw_hr_lbl = make_label("시간당 예상 비용: -", color=C["subtext"])
        pl.addWidget(self.pw_now_lbl)
        pl.addWidget(self.pw_cum_lbl)
        pl.addWidget(self.pw_hr_lbl)
        pl.addStretch()

        dp.addWidget(self._disk_grp, 3)
        dp.addWidget(pw_grp, 2)
        lay.addLayout(dp)

        # ── 프로세스 테이블
        tb = QHBoxLayout()
        tb.setSpacing(8)
        self.cpu_tbl = ProcessTable("🔥  CPU 상위 프로세스", mode="cpu")
        self.mem_tbl = ProcessTable("📦  메모리 상위 프로세스", mode="cpu")
        self.gpu_tbl = ProcessTable("🎮  GPU 상위 프로세스", mode="gpu")
        tb.addWidget(self.cpu_tbl)
        tb.addWidget(self.mem_tbl)
        tb.addWidget(self.gpu_tbl)
        lay.addLayout(tb)

        # ── AI 분석 박스
        lay.addWidget(make_label("🤖  AI 분석", color=C["green"], bold=True, size=12))
        self.analysis_box = QTextEdit()
        self.analysis_box.setReadOnly(True)
        self.analysis_box.setMinimumHeight(160)
        self.analysis_box.setPlainText("'지금 분석하기' 버튼을 누르거나 자동 분석을 켜면 AI 조언이 여기에 표시됩니다.")
        lay.addWidget(self.analysis_box)

        # ── AI 채팅
        lay.addWidget(make_label("💬  AI에게 질문하기", color=C["teal"], bold=True, size=12))
        chat_row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("예: 지금 CPU를 가장 많이 쓰는 프로세스가 뭔가요?")
        self.chat_input.setMinimumHeight(36)
        self.chat_send_btn = QPushButton("전송")
        self.chat_send_btn.setObjectName("sendBtn")
        self.chat_send_btn.setFixedWidth(72)
        self.chat_send_btn.setMinimumHeight(36)
        chat_row.addWidget(self.chat_input)
        chat_row.addWidget(self.chat_send_btn)
        lay.addLayout(chat_row)

        self.chat_box = QTextEdit()
        self.chat_box.setReadOnly(True)
        self.chat_box.setMinimumHeight(120)
        self.chat_box.setPlaceholderText("AI 응답이 여기에 표시됩니다.")
        lay.addWidget(self.chat_box)

        lay.addStretch()
        self.setWidget(root_w)

    # ── GPU 카드 갱신
    def update_gpu_cards(self, gpus: list):
        """GPU 카드를 이름으로 식별해 재사용한다.

        예전에는 카드를 리스트 위치로만 관리해서, 백엔드가 반환하는 GPU 순서가
        틱마다 달라지면(개수는 그대로인데 순서만 바뀌는 경우) 카드의 "GPU 0/1"
        제목은 그대로 둔 채 다른 GPU의 데이터를 그 카드에 채워 넣는 사고가 날 수
        있었다. 이름을 키로 써서 "이 카드는 항상 이 GPU"라는 정체성을 보장한다.
        """
        names_now = [g.get("name", "Unknown GPU") for g in gpus]

        # 레이아웃을 한 번 비운다(위젯은 아직 지우지 않는다 - 계속 쓸 카드도 있으므로).
        while self._gpu_row.count():
            self._gpu_row.takeAt(0)

        if not gpus:
            for card in self._gpu_cards.values():
                card.deleteLater()
            self._gpu_cards.clear()
            lbl = QLabel("GPU 정보 없음")
            lbl.setStyleSheet(f"color: {C['overlay0']}; padding: 8px;")
            self._gpu_row.addWidget(lbl)
            return

        # 더 이상 존재하지 않는 이름의 카드는 제거
        for stale_name in [n for n in self._gpu_cards if n not in names_now]:
            self._gpu_cards.pop(stale_name).deleteLater()

        for g in gpus:
            name = g.get("name", "Unknown GPU")
            card = self._gpu_cards.get(name)
            if card is None:
                card = GpuCard(g["index"])
                self._gpu_cards[name] = card
            card.update_data(g)
            self._gpu_row.addWidget(card)
        self._gpu_row.addStretch()

    # ── 디스크 갱신
    def update_disks(self, disks: list):
        if len(disks) != len(self._disk_ws):
            for w in self._disk_ws:
                w["lbl"].deleteLater()
                w["bar"].deleteLater()
            self._disk_ws.clear()

            for _ in disks:
                lbl = QLabel()
                lbl.setStyleSheet(f"color: {C['text']}; font-size: 9pt;")
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setFixedHeight(8)
                bar.setTextVisible(False)
                self._disk_lay.addWidget(lbl)
                self._disk_lay.addWidget(bar)
                self._disk_ws.append({"lbl": lbl, "bar": bar})

        for i, d in enumerate(disks):
            if i >= len(self._disk_ws):
                break
            pct = d["percent"]
            self._disk_ws[i]["lbl"].setText(
                f"{d['mount']}  {pct:.0f}%  ({d['used_gb']:.1f} / {d['total_gb']:.1f} GB)"
            )
            self._disk_ws[i]["bar"].setValue(int(min(pct, 100)))
            _set_bar_color(self._disk_ws[i]["bar"], _usage_color(pct))


# ─────────────────────────────────────────────────────────────
# 메인 윈도우
# ─────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("시스템 자원 AI 어드바이저")
        self.resize(1600, 920)
        self.setMinimumSize(1100, 680)

        self._monitor = ResourceMonitor()
        self._last_snap: dict | None = None
        self._last_analysis_time = 0.0
        self._analysis_running = False
        self._chat_running = False

        self._build_menubar()
        self._build_statusbar()

        # 중앙 위젯
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        self.sidebar = Sidebar()
        root.addWidget(self.sidebar)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; background: {C['crust']}; }}
            QTabBar::tab {{
                background: {C['mantle']}; color: {C['subtext']};
                padding: 8px 16px; border: none; margin-right: 2px;
            }}
            QTabBar::tab:selected {{ background: {C['surface0']}; color: {C['text']}; }}
            QTabBar::tab:hover {{ background: {C['surface0']}; }}
        """)
        root.addWidget(self.tabs, 1)

        self.dash = Dashboard()
        self.tabs.addTab(self.dash, "📊 모니터링")

        self.process_tab = ProcessOptimizationTab(lambda: self.sidebar.model, lambda: self.sidebar.temperature)
        self.tabs.addTab(self.process_tab, "⚙ 프로세스 최적화")

        self.storage_tab = StorageTab()
        self.tabs.addTab(self.storage_tab, "💾 저장공간")

        self.security_tab = SecurityTab(lambda: self.sidebar.model, lambda: self.sidebar.temperature)
        self.tabs.addTab(self.security_tab, "🛡 보안 프로그램")

        self.malware_tab = MalwareTab(lambda: self.sidebar.model)
        self.tabs.addTab(self.malware_tab, "🦠 악성파일")

        # 버튼 연결
        self.sidebar.analyze_btn.clicked.connect(self._start_analysis)
        self.dash.chat_send_btn.clicked.connect(self._start_chat)
        self.dash.chat_input.returnPressed.connect(self._start_chat)
        self.sidebar.ref_slider.valueChanged.connect(self._on_refresh_changed)

        # 타이머
        self._snap_timer = QTimer(self)
        self._snap_timer.timeout.connect(self._trigger_snapshot)
        self._snap_timer.start(self.sidebar.refresh_sec * 1000)

        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_tick)
        self._auto_timer.start(2000)

    # ── 메뉴바
    def _build_menubar(self):
        mb = self.menuBar()

        # 파일 메뉴
        file_menu = mb.addMenu("파일(&F)")
        act_exit = QAction("종료(&Q)", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # 보기 메뉴
        view_menu = mb.addMenu("보기(&V)")
        act_top = QAction("항상 위에 표시(&T)", self, checkable=True)
        act_top.triggered.connect(self._toggle_always_on_top)
        view_menu.addAction(act_top)
        self._act_top = act_top

        view_menu.addSeparator()
        act_refresh = QAction("지금 새로고침(&R)", self)
        act_refresh.setShortcut("F5")
        act_refresh.triggered.connect(self._trigger_snapshot)
        view_menu.addAction(act_refresh)

        # 분석 메뉴
        ai_menu = mb.addMenu("AI 분석(&A)")
        act_analyze = QAction("지금 분석하기(&A)", self)
        act_analyze.setShortcut("Ctrl+Return")
        act_analyze.triggered.connect(self._start_analysis)
        ai_menu.addAction(act_analyze)

        # 도움말 메뉴
        help_menu = mb.addMenu("도움말(&H)")
        act_about = QAction("이 프로그램 정보(&A)", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _build_statusbar(self):
        self._sb = QStatusBar()
        self.setStatusBar(self._sb)
        self._sb_snap_lbl = QLabel("대기 중...")
        self._sb.addWidget(self._sb_snap_lbl)
        self._sb.addPermanentWidget(QLabel("전력: Intel RAPL·NVIDIA·배터리 자동 측정"))

    def _toggle_always_on_top(self, checked: bool):
        flags = self.windowFlags()
        if checked:
            self.setWindowFlags(flags | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(flags & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()

    def _show_about(self):
        QMessageBox.about(
            self, "이 프로그램 정보",
            "<b>시스템 자원 AI 어드바이저</b><br><br>"
            "CPU / RAM / GPU / 디스크 실시간 모니터링 +<br>"
            "OpenRouter API를 통한 AI 분석 기능<br><br>"
            "전력은 Intel CPU(RAPL)·NVIDIA GPU·노트북 배터리에서<br>"
            "외부 도구 없이 자동 측정됩니다.<br>"
            "LHM(LibreHardwareMonitor)을 관리자 권한으로 실행하면<br>"
            "더 상세한 컴포넌트별 전력이 표시됩니다."
        )

    # ── 스냅샷
    def _on_refresh_changed(self, val: int):
        self._snap_timer.setInterval(val * 1000)

    def _trigger_snapshot(self):
        """ResourceMonitor.get_snapshot()은 백그라운드 수집 스레드가 채워둔 결과를
        락으로 잠깐 읽기만 하므로 항상 즉시 반환된다 — 더 이상 틱마다 QThread를
        새로 만들 필요가 없다(전에는 이 패턴이 COM 크로스스레드 행의 원인이었다)."""
        try:
            snap = self._monitor.get_snapshot()
        except Exception:
            snap = None
        self._apply_snapshot(snap)

    def _apply_snapshot(self, snap: dict):
        if not snap:
            self._sb_snap_lbl.setText("수집 실패")
            return

        self._last_snap = snap
        d = self.dash
        ts = snap.get("timestamp", "-")
        d.ts_lbl.setText(f"마지막 갱신: {ts}")
        self._sb_snap_lbl.setText(f"갱신됨: {ts}")

        # CPU
        cpu = snap.get("cpu_percent", 0.0)
        c = _usage_color(cpu)
        d.cpu_pct_lbl.setText(f"{cpu:.1f}%")
        d.cpu_pct_lbl.setStyleSheet(f"color: {c}; font-weight: bold; font-size: 12pt;")
        d.cpu_bar.setValue(int(min(cpu, 100)))
        _set_bar_color(d.cpu_bar, c)

        # RAM
        mp = snap.get("mem_percent", 0.0)
        mc = _usage_color(mp)
        d.ram_pct_lbl.setText(f"{mp:.1f}%")
        d.ram_pct_lbl.setStyleSheet(f"color: {mc}; font-weight: bold; font-size: 12pt;")
        d.ram_bar.setValue(int(min(mp, 100)))
        _set_bar_color(d.ram_bar, mc)
        d.ram_detail_lbl.setText(f"{snap.get('mem_used_gb', 0):.1f} / {snap.get('mem_total_gb', 0):.1f} GB")

        # GPU
        d.update_gpu_cards(snap.get("gpus", []))

        # 디스크
        d.update_disks(snap.get("disks", []))

        # 전력
        pw = snap.get("total_power_w")
        rate = self.sidebar.electricity_rate
        if pw is not None:
            cwh = snap.get("cumulative_wh", 0.0)
            d.pw_now_lbl.setText(f"소비 전력: {pw:.1f} W")
            d.pw_now_lbl.setStyleSheet(f"color: {C['yellow']};")
            d.pw_cum_lbl.setText(f"누적: {cwh:.1f} Wh / {(cwh/1000)*rate:.1f}원")
            d.pw_hr_lbl.setText(f"시간당 예상: {(pw/1000)*rate:.1f}원")
        else:
            d.pw_now_lbl.setText("소비 전력: N/A  (전력 센서 미지원 · LHM 관리자 실행 시 측정)")
            d.pw_now_lbl.setStyleSheet(f"color: {C['overlay0']};")
            d.pw_cum_lbl.setText("누적 사용량/비용: -")
            d.pw_hr_lbl.setText("시간당 예상 비용: -")

        # 프로세스 테이블
        d.cpu_tbl.fill(
            snap.get("top_cpu", []),
            lambda r: (r["name"], r["pid"], f"{r['cpu_percent']:.1f}", f"{r['mem_percent']:.1f}")
        )
        d.mem_tbl.fill(
            snap.get("top_mem", []),
            lambda r: (r["name"], r["pid"], f"{r['cpu_percent']:.1f}", f"{r['mem_percent']:.1f}")
        )
        d.gpu_tbl.fill(
            snap.get("gpu_processes", []),
            lambda r: (r["name"], r["pid"], f"{r['gpu_percent']:.1f}")
        )

    # ── 자동 분석
    def _auto_tick(self):
        if not self.sidebar.auto_analyze or self._analysis_running:
            return
        if time.time() - self._last_analysis_time >= self.sidebar.ai_interval_sec:
            self._start_analysis()

    # ── AI 분석
    def _start_analysis(self):
        if self._analysis_running:
            return
        if not OPENROUTER_API_KEY:
            self.sidebar.status_lbl.setText("⚠ OPENROUTER_API_KEY 없음")
            self.sidebar.status_lbl.setStyleSheet(f"color: {C['pink']}; font-size: 9pt;")
            return
        if self._last_snap is None:
            self.sidebar.status_lbl.setText("데이터 수집 대기 중...")
            return

        self._analysis_running = True
        self.sidebar.analyze_btn.setEnabled(False)
        self.sidebar.status_lbl.setText("AI 분석 중...")
        self.sidebar.status_lbl.setStyleSheet(f"color: {C['green']}; font-size: 9pt;")

        snap_text = snapshot_to_text(self._last_snap, self.sidebar.electricity_rate)

        t = QThread(self)
        w = LLMWorker(ask_llm, snap_text, self.sidebar.model, self.sidebar.temperature)
        w.moveToThread(t)
        t.started.connect(w.run)
        w.result.connect(self._apply_analysis)
        w.result.connect(t.quit)
        t.finished.connect(t.deleteLater)
        w.result.connect(w.deleteLater)
        self._llm_thread = (t, w)
        t.start()

    def _apply_analysis(self, result: str):
        self._analysis_running = False
        self._last_analysis_time = time.time()
        self.sidebar.analyze_btn.setEnabled(True)
        self.sidebar.status_lbl.setText("")
        self.dash.analysis_box.setPlainText(result)

    # ── AI 채팅
    def _start_chat(self):
        if self._chat_running:
            return
        question = self.dash.chat_input.text().strip()
        if not question:
            return
        if not OPENROUTER_API_KEY:
            self.dash.chat_box.setPlainText("⚠ OPENROUTER_API_KEY가 없습니다.")
            return

        self._chat_running = True
        self.dash.chat_send_btn.setEnabled(False)
        self.dash.chat_input.setEnabled(False)
        self.dash.chat_box.setPlainText("AI가 답변 중입니다...")

        snap_text = snapshot_to_text(self._last_snap, self.sidebar.electricity_rate) if self._last_snap else ""

        t = QThread(self)
        w = LLMWorker(ask_llm_question, snap_text, question, self.sidebar.model, self.sidebar.temperature)
        w.moveToThread(t)
        t.started.connect(w.run)
        w.result.connect(self._apply_chat)
        w.result.connect(t.quit)
        t.finished.connect(t.deleteLater)
        w.result.connect(w.deleteLater)
        self._chat_thread = (t, w)
        t.start()

    def _apply_chat(self, result: str):
        self._chat_running = False
        self.dash.chat_send_btn.setEnabled(True)
        self.dash.chat_input.setEnabled(True)
        self.dash.chat_box.setPlainText(result)
        self.dash.chat_input.clear()

    def closeEvent(self, event):
        self._snap_timer.stop()
        self._auto_timer.stop()
        event.accept()


# ─────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
