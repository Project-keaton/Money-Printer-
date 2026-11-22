"""Download summary report: printed to the console and saved to ``reports/``."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from data_pipeline.config import PROJECT_ROOT, Timeframe
from data_pipeline.storage import YearFile
from data_pipeline.transforms import FoldReport

log = logging.getLogger(__name__)

_WIDTH = 72


@dataclass
class DownloadSummary:
    provider: str
    symbol: str
    timeframe: Timeframe
    requested_start: date
    requested_end: date
    data_start: pd.Timestamp | None
    data_end: pd.Timestamp | None
    records_downloaded: int
    records_saved: int
    duplicates_removed: int
    invalid_rows_removed: int
    files: list[YearFile]
    duration_seconds: float
    failed_requests: list[str] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    other_warnings: list[str] = field(default_factory=list)
    weekday_files: list[YearFile] = field(default_factory=list)
    fold: FoldReport | None = None
    generated_at: datetime = field(default_factory=datetime.now)

    @property
    def status(self) -> str:
        if self.failed_requests:
            return "PARTIAL - some requests failed (see failed requests below)"
        if self.missing_data_warnings:
            return "COMPLETE WITH WARNINGS"
        return "COMPLETE"

    def render(self, max_items: int = 25) -> str:
        """Plain-text report. Long lists are truncated (the full detail is in the log file)."""
        fmt = self.timeframe.date_format
        first = f"{self.data_start:{fmt}}" if self.data_start is not None else "n/a"
        last = f"{self.data_end:{fmt}}" if self.data_end is not None else "n/a"

        lines = [
            "=" * _WIDTH,
            f" {self.symbol} HISTORICAL DATA DOWNLOAD SUMMARY",
            "=" * _WIDTH,
            _row("Status", self.status),
            _row("Provider", self.provider),
            _row("Timeframe", self.timeframe.value),
            _row("Requested range", f"{self.requested_start} -> {self.requested_end}"),
            _row("Start Date", first),
            _row("End Date", last),
            _row("Total Records Downloaded", f"{self.records_downloaded:,}"),
            _row("Records Saved", f"{self.records_saved:,}"),
            _row("Duplicates Removed", f"{self.duplicates_removed:,}"),
            _row("Invalid Rows Removed", f"{self.invalid_rows_removed:,}"),
            _row("Total Files Created", str(len(self.files))),
            _row("Failed Requests", str(len(self.failed_requests))),
            _row("Missing Data Warnings", str(len(self.missing_data_warnings))),
            _row("Duration", f"{self.duration_seconds:.1f}s"),
            "-" * _WIDTH,
            " Files:",
        ]
        for f in self.files:
            lines.append(f"   {_display_path(f.path):<28} {f.rows:>7,} rows   {f.first:{fmt}} -> {f.last:{fmt}}")
        if not self.files:
            lines.append("   (none)")

        if self.fold is not None:
            lines += ["-" * _WIDTH, *render_comparison(self.files, self.weekday_files, self.fold, fmt)]

        for title, items in (
            ("Failed requests", self.failed_requests),
            ("Missing data warnings", self.missing_data_warnings),
            ("Other warnings", self.other_warnings),
        ):
            if items:
                lines += ["-" * _WIDTH, f" {title}:"]
                lines += [f"   - {item}" for item in items[:max_items]]
                if len(items) > max_items:
                    lines.append(f"   ... and {len(items) - max_items} more (see logs/data_download.log)")

        lines += ["=" * _WIDTH, f" Generated {self.generated_at:%Y-%m-%d %H:%M:%S}"]
        return "\n".join(lines)


def render_comparison(
    raw_files: list[YearFile], weekday_files: list[YearFile], fold: FoldReport, fmt: str = "%Y-%m-%d"
) -> list[str]:
    """Side-by-side row counts of the raw and Monday-Friday datasets."""
    lines = [
        " Monday-Friday dataset (Sunday candles folded into Monday):",
        f"   Sunday candles folded : {fold.sundays_folded:,}",
        f"   Unmatched Sundays     : {len(fold.unmatched_sundays)} (dropped)"
        + (f" - {', '.join(fold.unmatched_sundays[:5])}" if fold.unmatched_sundays else ""),
        f"   Total rows            : {fold.input_rows:,} raw -> {fold.output_rows:,} weekday",
        "",
        f"   {'Year':<6} {'Raw rows':>9} {'Weekday rows':>13}   Weekday file",
    ]
    weekday_by_year = {f.year: f for f in weekday_files}
    years = sorted({f.year for f in raw_files} | set(weekday_by_year))
    raw_by_year = {f.year: f for f in raw_files}
    for year in years:
        raw = raw_by_year.get(year)
        wk = weekday_by_year.get(year)
        lines.append(
            f"   {year:<6} {raw.rows if raw else 0:>9,} {wk.rows if wk else 0:>13,}   "
            f"{_display_path(wk.path) if wk else '(none)'}"
        )
    return lines


def save_report(summary: DownloadSummary, report_dir: Path) -> Path:
    """Write the full (untruncated) report to ``reports/`` and return its path."""
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{summary.symbol}_download_summary_{summary.generated_at:%Y%m%d_%H%M%S}.txt"
    path.write_text(summary.render(max_items=10_000) + "\n", encoding="utf-8")
    log.info("Summary report saved to %s", path)
    return path


def _row(label: str, value: str) -> str:
    return f" {label:<26}: {value}"


def _display_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)
