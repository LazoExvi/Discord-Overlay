"""First-run region selection plus a measured OCR capability test."""
from __future__ import annotations

import queue
import threading
import tkinter as tk

import customtkinter as ctk

from ..models import Region
from ..performance import SLOW_PROFILES, CapabilityResult, benchmark_capability, faster_result
from . import theme


class HardwareSetupWizard(ctk.CTkToplevel):
    def __init__(self, parent, region: Region | None, select_region, apply_result) -> None:
        super().__init__(parent, fg_color=theme.BG)
        self.region = region
        self.select_region = select_region
        self.apply_result = apply_result
        self.result: CapabilityResult | None = None
        self.gpu_result: CapabilityResult | None = None
        self.results: queue.Queue = queue.Queue()
        self.title("Discord Overlay First-Time Setup")
        self.geometry("760x650")
        self.minsize(680, 600)
        self.transient(parent)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        theme.heading(self, "FIRST-TIME OCR SETUP", 22).grid(row=0, column=0, padx=28, pady=(24, 10), sticky="ew")
        body = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=12)
        body.grid(row=1, column=0, padx=24, pady=8, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        theme.note(body, ("Discord Overlay measures this computer instead of guessing from the video-card name. "
                          "The result sets a safe default scan rate and warns when heavy combat may scroll "
                          "faster than OCR."), 660, theme.TEXT).grid(row=0, column=0, padx=22, pady=(20, 14), sticky="ew")

        region_card = self._card(body, 1, "1  COMBAT REGION")
        self.region_label = ctk.CTkLabel(region_card, text=self._region_text(), text_color=theme.MUTED, anchor="w")
        self.region_label.grid(row=1, column=0, padx=16, pady=(0, 13), sticky="ew")
        ctk.CTkButton(region_card, text="Select region", width=120, command=self._choose_region,
                      **theme.ACCENT_BUTTON).grid(row=0, column=1, rowspan=2, padx=14, pady=12)

        test_card = self._card(body, 2, "2  HARDWARE CAPABILITY TEST")
        self.test_status = ctk.CTkLabel(test_card, text="Ready to test" if region else "Select the combat region first",
                                        text_color=theme.MUTED, anchor="w")
        self.test_status.grid(row=1, column=0, padx=16, pady=(0, 6), sticky="ew")
        self.progress = ctk.CTkProgressBar(test_card, mode="indeterminate", progress_color=theme.ACCENT)
        self.progress.grid(row=2, column=0, columnspan=2, padx=16, pady=(2, 14), sticky="ew")
        self.progress.set(0)
        self.test_button = ctk.CTkButton(test_card, text="Run capability test", width=150, command=self._run_test,
                                         state="normal" if region else "disabled", **theme.ACCENT_BUTTON)
        self.test_button.grid(row=0, column=1, rowspan=2, padx=14, pady=12)

        result_card = self._card(body, 3, "3  RECOMMENDATION")
        self.result_label = ctk.CTkLabel(result_card, text="Run the test to generate a measured recommendation.",
                                         text_color=theme.MUTED, justify="left", anchor="nw", wraplength=650,
                                         font=theme.font(13))
        self.result_label.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="ew")
        self.compare_button = ctk.CTkButton(result_card, text="Compare with CPU", width=150,
                                            command=lambda: self._run_test(False), **theme.STEEL_BUTTON)

        theme.note(body, ("The benchmark uses a dense synthetic combat panel and your real screen-capture region. "
                          "No game process, log, or memory is accessed."), 660, theme.DIM).grid(
            row=4, column=0, padx=22, pady=(10, 18), sticky="ew")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, padx=24, pady=(8, 22), sticky="ew")
        ctk.CTkButton(footer, text="Skip for now", command=self.destroy, width=110, **theme.QUIET_BUTTON).pack(
            side="right", padx=5)
        self.apply_button = ctk.CTkButton(footer, text="Apply recommended settings", command=self._apply, width=190,
                                          state="disabled", **theme.ACCENT_BUTTON)
        self.apply_button.pack(side="right", padx=5)
        self.after(100, self._activate)
        self.after(100, self._poll_results)

    @staticmethod
    def _card(body, row: int, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(body, fg_color=theme.PANEL_2, corner_radius=9)
        card.grid(row=row, column=0, padx=18, pady=8, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, text_color=theme.ACCENT, font=theme.font(bold=True), anchor="w").grid(
            row=0, column=0, padx=16, pady=(13, 2), sticky="ew")
        return card

    def _activate(self) -> None:
        if self.winfo_exists():
            self.attributes("-topmost", True)
            theme.bring_to_front(self)
            self.grab_set()

    def _region_text(self) -> str:
        return self.region.describe() if self.region else "No combat region selected."

    def _choose_region(self) -> None:
        theme.release_grab(self)
        self.select_region(self._region_selected)

    def _region_selected(self, region: Region) -> None:
        self.region = region
        self.region_label.configure(text=self._region_text())
        self.test_status.configure(text="Region selected — starting test...", text_color=theme.ACCENT)
        self.test_button.configure(state="normal")
        self.after(100, self._activate)
        self.after(250, self._run_test)

    def _run_test(self, prefer_gpu: bool = True) -> None:
        if not self.region:
            return
        if prefer_gpu:
            self.result = self.gpu_result = None
        self.compare_button.grid_remove()
        self.test_button.configure(state="disabled")
        self.apply_button.configure(state="disabled")
        mode = "GPU" if prefer_gpu else "CPU"
        self.test_status.configure(text=f"Loading {mode} OCR models and measuring performance...",
                                   text_color=theme.ACCENT)
        self.result_label.configure(text=f"The {mode} test may take several seconds while the OCR models initialize.",
                                    text_color=theme.MUTED)
        self.progress.start()

        def work() -> None:
            try:
                self.results.put(("result", prefer_gpu, benchmark_capability(self.region, prefer_gpu=prefer_gpu)))
            except Exception as exc:  # noqa: BLE001 - shown to the user
                self.results.put(("error", prefer_gpu, f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=work, name="capability-benchmark", daemon=True).start()

    def _poll_results(self) -> None:
        try:
            kind, prefer_gpu, value = self.results.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(100, self._poll_results)
            return
        self.progress.stop()
        self.progress.set(1 if kind == "result" else 0)
        self.test_button.configure(state="normal")
        if kind == "error":
            if not prefer_gpu and self.gpu_result:
                self.result = self.gpu_result
                self.test_status.configure(text="CPU comparison failed — keeping GPU result", text_color=theme.RED)
                self.result_label.configure(text=f"CPU test failed: {value}\n\nThe measured GPU recommendation "
                                                 "is still available.", text_color=theme.RED)
                self.apply_button.configure(state="normal")
            else:
                self.test_status.configure(text="Capability test failed", text_color=theme.RED)
                self.result_label.configure(text=value, text_color=theme.RED)
        else:
            if prefer_gpu and value.provider == "GPU":
                self.gpu_result = value
            if not prefer_gpu and self.gpu_result:
                self.result = faster_result(self.gpu_result, value)
                self.test_status.configure(text=f"Comparison complete — {self.result.provider} recommended",
                                           text_color=theme.GREEN)
                self.result_label.configure(text=self._comparison_details(self.gpu_result, value, self.result),
                                            text_color=theme.RED if self.result.warning else theme.TEXT)
            else:
                self.result = value
                details = self._result_details(value)
                if value.provider == "GPU" and value.profile in SLOW_PROFILES:
                    details += ("\n\nThis GPU is in a slower OCR tier. Compare it with the CPU; "
                                "the setup will keep whichever completes full scans faster.")
                    self.compare_button.grid(row=2, column=0, padx=16, pady=(0, 14), sticky="w")
                self.test_status.configure(text="Capability test complete", text_color=theme.GREEN)
                self.result_label.configure(text=details, text_color=theme.RED if value.warning else theme.TEXT)
            self.apply_button.configure(state="normal")
        if self.winfo_exists():
            self.after(100, self._poll_results)

    @staticmethod
    def _result_details(value: CapabilityResult) -> str:
        details = (
            f"Detected: {', '.join(value.gpu_names) or 'No supported GPU name reported'}\n"
            f"OCR backend: {value.provider} ({value.provider_detail})\n"
            f"Dense-panel OCR: {value.ocr_ms:.0f} ms  |  Capture: {value.capture_ms:.0f} ms\n"
            f"Benchmark lines recognized: {value.recognized_lines}\n"
            f"Estimated full scans: {value.full_scan_fps:.1f}/sec  |  Change checks: {value.change_check_fps:.1f}/sec\n\n"
            f"Recommended profile: {value.profile}\n"
            f"Scan interval: {value.recommended_interval:.2f} seconds"
        )
        return details + (f"\n\nWARNING: {value.warning}" if value.warning else "")

    @staticmethod
    def _comparison_details(gpu: CapabilityResult, cpu: CapabilityResult, chosen: CapabilityResult) -> str:
        details = (
            f"GPU ({gpu.provider_detail}): {gpu.full_scan_ms:.0f} ms per full scan  |  {gpu.full_scan_fps:.1f}/sec\n"
            f"CPU ({cpu.provider_detail}): {cpu.full_scan_ms:.0f} ms per full scan  |  {cpu.full_scan_fps:.1f}/sec\n\n"
            f"Recommended: {chosen.provider} ({chosen.provider_detail})\n"
            f"Profile: {chosen.profile}  |  Scan interval: {chosen.recommended_interval:.2f} seconds"
        )
        return details + (f"\n\nWARNING: {chosen.warning}" if chosen.warning else "")

    def _apply(self) -> None:
        if self.result:
            self.apply_result(self.result)
            self.destroy()
