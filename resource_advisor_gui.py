import threading
import time
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from resource_core import OPENROUTER_API_KEY, AVAILABLE_MODELS, ResourceMonitor, snapshot_to_text, ask_llm

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _style_treeview():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Treeview",
        background="#2b2b2b",
        foreground="white",
        fieldbackground="#2b2b2b",
        bordercolor="#2b2b2b",
        rowheight=22
    )
    style.configure("Treeview.Heading", background="#1f6aa5", foreground="white")
    style.map("Treeview", background=[("selected", "#144870")])


class ResourceAdvisorApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("시스템 자원 AI 어드바이저")
        self.geometry("1150x760")
        _style_treeview()

        self.monitor = ResourceMonitor()
        self.last_snapshot = None
        self.last_analysis_time = 0.0
        self._refresh_in_progress = False
        self._analysis_in_progress = False

        self._build_layout()

        self._schedule_dashboard_refresh()
        self._schedule_auto_analysis()

    # -----------------------------------------------------
    # 레이아웃 구성
    # -----------------------------------------------------
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main()

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=260)
        sidebar.grid(row=0, column=0, sticky="ns", padx=10, pady=10)

        ctk.CTkLabel(sidebar, text="설정", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(10, 20))

        ctk.CTkLabel(sidebar, text="사용 모델").pack(anchor="w", padx=15)
        self.model_var = tk.StringVar(value=AVAILABLE_MODELS[0])
        ctk.CTkOptionMenu(sidebar, values=AVAILABLE_MODELS, variable=self.model_var).pack(fill="x", padx=15, pady=(0, 15))

        ctk.CTkLabel(sidebar, text="Temperature").pack(anchor="w", padx=15)
        self.temperature_var = tk.DoubleVar(value=0.3)
        ctk.CTkSlider(sidebar, from_=0.0, to=1.0, variable=self.temperature_var).pack(fill="x", padx=15, pady=(0, 15))

        ctk.CTkLabel(sidebar, text="대시보드 새로고침 주기 (초)").pack(anchor="w", padx=15)
        self.refresh_interval_var = tk.IntVar(value=1)
        ctk.CTkSlider(
            sidebar, from_=1, to=30, number_of_steps=29, variable=self.refresh_interval_var
        ).pack(fill="x", padx=15, pady=(0, 15))

        self.auto_analyze_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(sidebar, text="AI 자동 분석", variable=self.auto_analyze_var).pack(anchor="w", padx=15, pady=(10, 15))

        ctk.CTkLabel(sidebar, text="AI 분석 주기 (초)").pack(anchor="w", padx=15)
        self.analysis_interval_var = tk.IntVar(value=60)
        ctk.CTkSlider(
            sidebar, from_=30, to=600, number_of_steps=19, variable=self.analysis_interval_var
        ).pack(fill="x", padx=15, pady=(0, 15))

        self.analyze_button = ctk.CTkButton(sidebar, text="지금 분석하기", command=lambda: self._start_analysis(manual=True))
        self.analyze_button.pack(fill="x", padx=15, pady=(10, 5))

        self.status_label = ctk.CTkLabel(sidebar, text="", text_color="gray", wraplength=220, justify="left")
        self.status_label.pack(padx=15, pady=(5, 15))

        if not OPENROUTER_API_KEY:
            ctk.CTkLabel(
                sidebar,
                text="⚠ .env에 OPENROUTER_API_KEY가 없습니다.",
                text_color="orange",
                wraplength=220
            ).pack(padx=15)

        ctk.CTkLabel(
            sidebar,
            text="OpenRouter API를 사용하므로\n분석 요청마다 비용이 발생할 수 있습니다.",
            text_color="gray",
            font=ctk.CTkFont(size=11),
            wraplength=220,
            justify="left"
        ).pack(side="bottom", padx=15, pady=10)

    def _build_main(self):
        main = ctk.CTkFrame(self)
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=10)
        main.grid_columnconfigure((0, 1), weight=1)
        main.grid_rowconfigure(5, weight=1)
        main.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(
            main, text="시스템 자원 AI 어드바이저", font=ctk.CTkFont(size=20, weight="bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=15, pady=(15, 0))

        self.last_update_label = ctk.CTkLabel(main, text="마지막 갱신: -", text_color="gray")
        self.last_update_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=15, pady=(0, 10))

        self.cpu_label = ctk.CTkLabel(main, text="CPU 사용률: -")
        self.cpu_label.grid(row=2, column=0, sticky="w", padx=15)
        self.cpu_bar = ctk.CTkProgressBar(main)
        self.cpu_bar.set(0)
        self.cpu_bar.grid(row=3, column=0, sticky="ew", padx=15, pady=(0, 10))

        self.mem_label = ctk.CTkLabel(main, text="RAM 사용률: -")
        self.mem_label.grid(row=2, column=1, sticky="w", padx=15)
        self.mem_bar = ctk.CTkProgressBar(main)
        self.mem_bar.set(0)
        self.mem_bar.grid(row=3, column=1, sticky="ew", padx=15, pady=(0, 10))

        self.resource_frame = ctk.CTkFrame(main, fg_color="transparent")
        self.resource_frame.grid(row=4, column=0, columnspan=2, sticky="ew", padx=15, pady=(0, 10))

        tables_frame = ctk.CTkFrame(main, fg_color="transparent")
        tables_frame.grid(row=5, column=0, columnspan=2, sticky="nsew", padx=15, pady=(0, 10))
        tables_frame.grid_columnconfigure((0, 1), weight=1)
        tables_frame.grid_rowconfigure(0, weight=1)

        cpu_frame, self.cpu_tree = self._make_process_table(tables_frame, "CPU 사용량 상위 프로세스")
        cpu_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        mem_frame, self.mem_tree = self._make_process_table(tables_frame, "메모리 사용량 상위 프로세스")
        mem_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        ctk.CTkLabel(
            main, text="AI 분석", font=ctk.CTkFont(size=15, weight="bold")
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=15, pady=(10, 0))

        self.analysis_box = ctk.CTkTextbox(main, wrap="word")
        self.analysis_box.grid(row=7, column=0, columnspan=2, sticky="nsew", padx=15, pady=(0, 15))
        self.analysis_box.insert("1.0", "‘지금 분석하기’ 버튼을 누르거나 자동 분석을 켜면 AI 조언이 여기에 표시됩니다.")
        self.analysis_box.configure(state="disabled")

    def _make_process_table(self, parent, title):
        frame = ctk.CTkFrame(parent)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(8, 4))

        columns = ("name", "pid", "cpu", "mem")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        tree.heading("name", text="이름")
        tree.heading("pid", text="PID")
        tree.heading("cpu", text="CPU %")
        tree.heading("mem", text="MEM %")
        tree.column("name", width=150)
        tree.column("pid", width=60, anchor="center")
        tree.column("cpu", width=70, anchor="e")
        tree.column("mem", width=70, anchor="e")
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        return frame, tree

    # -----------------------------------------------------
    # 대시보드 갱신 (백그라운드 스레드에서 수집, 메인 스레드에서 반영)
    # -----------------------------------------------------
    def _schedule_dashboard_refresh(self):
        if not self._refresh_in_progress:
            self._refresh_in_progress = True
            threading.Thread(target=self._collect_snapshot, daemon=True).start()

        interval_ms = max(1, self.refresh_interval_var.get()) * 1000
        self.after(interval_ms, self._schedule_dashboard_refresh)

    def _collect_snapshot(self):
        try:
            snap = self.monitor.get_snapshot()
        except Exception:
            snap = None
        self.after(0, self._apply_snapshot, snap)

    def _apply_snapshot(self, snap):
        self._refresh_in_progress = False
        if snap is None:
            return

        self.last_snapshot = snap
        self.last_update_label.configure(text=f"마지막 갱신: {snap['timestamp']}")

        self.cpu_label.configure(text=f"CPU 사용률: {snap['cpu_percent']:.1f}%")
        self.cpu_bar.set(min(snap["cpu_percent"] / 100, 1.0))

        self.mem_label.configure(
            text=f"RAM 사용률: {snap['mem_percent']:.1f}% ({snap['mem_used_gb']:.1f} / {snap['mem_total_gb']:.1f} GB)"
        )
        self.mem_bar.set(min(snap["mem_percent"] / 100, 1.0))

        self._update_resource_frame(snap)
        self._fill_tree(self.cpu_tree, snap["top_cpu"])
        self._fill_tree(self.mem_tree, snap["top_mem"])

    def _update_resource_frame(self, snap):
        disks = snap["disks"]
        gpus = snap["gpus"]

        # 캐시 변수들이 없거나 개수가 다르면 완전히 새로 그린다
        if (
            not hasattr(self, "disk_ui")
            or len(self.disk_ui) != len(disks)
            or not hasattr(self, "gpu_ui")
            or len(self.gpu_ui) != len(gpus or [])
        ):
            for widget in self.resource_frame.winfo_children():
                widget.destroy()
            self.disk_ui = []
            self.gpu_ui = []

            self.resource_frame.grid_columnconfigure(tuple(range(max(len(disks), 1))), weight=1)

            # 디스크 타이틀
            ctk.CTkLabel(self.resource_frame, text="디스크", font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=0, sticky="w", pady=(5, 0)
            )
            # 디스크 위젯 생성
            for i, d in enumerate(disks):
                box = ctk.CTkFrame(self.resource_frame, fg_color="transparent")
                box.grid(row=1, column=i, sticky="ew", padx=(0, 10))
                lbl = ctk.CTkLabel(box, text="")
                lbl.pack(anchor="w")
                bar = ctk.CTkProgressBar(box)
                bar.pack(fill="x", pady=(2, 0))
                self.disk_ui.append({"label": lbl, "bar": bar})

            # GPU 타이틀
            ctk.CTkLabel(self.resource_frame, text="GPU", font=ctk.CTkFont(weight="bold")).grid(
                row=2, column=0, sticky="w", pady=(10, 0)
            )
            # GPU 위젯 생성
            if gpus:
                for i, g in enumerate(gpus):
                    box = ctk.CTkFrame(self.resource_frame, fg_color="transparent")
                    box.grid(row=3, column=i, sticky="ew", padx=(0, 10))
                    lbl = ctk.CTkLabel(box, text="")
                    lbl.pack(anchor="w")
                    bar = ctk.CTkProgressBar(box)
                    bar.pack(fill="x", pady=(2, 0))
                    self.gpu_ui.append({"label": lbl, "bar": bar})
            else:
                lbl = ctk.CTkLabel(
                    self.resource_frame, text="GPU 정보를 가져올 수 없습니다 (NVIDIA GPU + nvidia-smi 필요).", text_color="gray"
                )
                lbl.grid(row=3, column=0, sticky="w")

        # 기존 캐시된 위젯의 데이터만 실시간 업데이트 (깜빡임과 버벅임 제거!)
        for i, d in enumerate(disks):
            self.disk_ui[i]["label"].configure(text=f"{d['mount']}  {d['percent']:.0f}%  ({d['used_gb']:.1f}/{d['total_gb']:.1f} GB)")
            self.disk_ui[i]["bar"].set(min(d["percent"] / 100, 1.0))

        if gpus:
            for i, g in enumerate(gpus):
                if g.get("static_only"):
                    text = f"{g['name']}  VRAM: {g['mem_total_mb']:.0f} MB (하드웨어만 감지됨)"
                    val = 0.0
                else:
                    text = f"{g['name']}  {g['util_percent']:.0f}%  ({g['mem_used_mb']:.0f}/{g['mem_total_mb']:.0f} MB, {g['temp_c']:.0f}C)"
                    val = min(g["util_percent"] / 100, 1.0)
                self.gpu_ui[i]["label"].configure(text=text)
                self.gpu_ui[i]["bar"].set(val)

    @staticmethod
    def _fill_tree(tree, rows):
        tree.delete(*tree.get_children())
        for r in rows:
            tree.insert("", "end", values=(r["name"], r["pid"], f"{r['cpu_percent']:.1f}", f"{r['mem_percent']:.1f}"))

    # -----------------------------------------------------
    # AI 분석
    # -----------------------------------------------------
    def _schedule_auto_analysis(self):
        if self.auto_analyze_var.get() and not self._analysis_in_progress:
            elapsed = time.time() - self.last_analysis_time
            if elapsed >= self.analysis_interval_var.get():
                self._start_analysis(manual=False)
        self.after(2000, self._schedule_auto_analysis)

    def _start_analysis(self, manual):
        if self._analysis_in_progress:
            return

        if not OPENROUTER_API_KEY:
            self._set_status("⚠ .env에 OPENROUTER_API_KEY가 설정되어 있지 않습니다.", "orange")
            return

        if self.last_snapshot is None:
            if manual:
                self._set_status("아직 수집된 자원 데이터가 없습니다. 잠시 후 다시 시도하세요.", "orange")
            return

        self._analysis_in_progress = True
        self.analyze_button.configure(state="disabled")
        self._set_status("AI가 자원 사용 현황을 분석하고 있습니다...", "gray")

        snapshot_text = snapshot_to_text(self.last_snapshot)
        model = self.model_var.get()
        temperature = self.temperature_var.get()

        threading.Thread(
            target=self._run_analysis_worker, args=(snapshot_text, model, temperature), daemon=True
        ).start()

    def _run_analysis_worker(self, snapshot_text, model, temperature):
        try:
            result = ask_llm(snapshot_text, model, temperature)
        except Exception as e:
            result = f"분석 중 오류가 발생했습니다: {e}"
        self.after(0, self._apply_analysis, result)

    def _apply_analysis(self, result):
        self._analysis_in_progress = False
        self.last_analysis_time = time.time()
        self.analyze_button.configure(state="normal")
        self._set_status("", "gray")

        self.analysis_box.configure(state="normal")
        self.analysis_box.delete("1.0", "end")
        self.analysis_box.insert("1.0", result)
        self.analysis_box.configure(state="disabled")

    def _set_status(self, text, color):
        self.status_label.configure(text=text, text_color=color)


if __name__ == "__main__":
    app = ResourceAdvisorApp()
    app.mainloop()
