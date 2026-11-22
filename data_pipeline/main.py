"""Command-line entry point for the historical data pipeline.

Usage (from the ForexBot project root)::

    python -m data_pipeline                 # download using settings from .env
    python -m data_pipeline --provider oanda --timeframe 1h
    python -m data_pipeline --verify        # check the yearly CSV files

Exit codes:
    0  success
    1  finished, but some requests failed or verification found problems
    2  configuration error
    3  download failed (authentication error, provider unavailable, no data)
    130 interrupted with Ctrl+C
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from contextlib import closing
from pathlib import Path

import pandas as pd

from data_pipeline.config import (
    DEFAULT_ENV_FILE,
    DEFAULT_HISTORY_YEARS,
    PROVIDER_API_KEY_ENV,
    ConfigError,
    Settings,
    Timeframe,
    load_settings,
)
from data_pipeline.downloader import DownloadError, ForexDownloader
from data_pipeline.logger import setup_logging
from data_pipeline.providers import AuthenticationError, ProviderError, create_provider
from data_pipeline.report import DownloadSummary, save_report
from data_pipeline.report import render_comparison
from data_pipeline.storage import (
    YearFile,
    load_yearly_csv,
    verify_yearly_files,
    write_yearly_csv,
    yearly_filename,
)
from data_pipeline.transforms import FoldReport, fold_sundays_into_monday
from data_pipeline.validator import DataValidationError, validate_ohlcv

EXIT_OK, EXIT_PARTIAL, EXIT_CONFIG, EXIT_FAILED, EXIT_INTERRUPTED = 0, 1, 2, 3, 130

log = logging.getLogger("data_pipeline")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m data_pipeline",
        description="Download historical forex candles and save one CSV per year.",
    )
    parser.add_argument("--provider", choices=sorted(PROVIDER_API_KEY_ENV), help="override DATA_PROVIDER")
    parser.add_argument("--timeframe", choices=[t.value for t in Timeframe], help="override DATA_TIMEFRAME")
    parser.add_argument("--start", metavar="YYYY-MM-DD", help="override DATA_START_DATE")
    parser.add_argument("--end", metavar="YYYY-MM-DD", help="override DATA_END_DATE")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="path to the .env file")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="override LOG_LEVEL")
    parser.add_argument("--no-progress", action="store_true", help="hide the progress bar")
    parser.add_argument("--verify", action="store_true", help="only verify existing yearly CSV files")
    parser.add_argument(
        "--build-weekday",
        action="store_true",
        help="rebuild the Monday-Friday dataset from the existing daily CSV files (no download)",
    )
    return parser.parse_args(argv)


def build_weekday_dataset(settings: Settings, daily: pd.DataFrame) -> tuple[list[YearFile], FoldReport]:
    """Fold Sunday candles into Monday and write the result to ``settings.weekday_data_dir``."""
    weekday, fold = fold_sundays_into_monday(daily)
    files = write_yearly_csv(weekday, settings.weekday_data_dir, settings.symbol, settings.timeframe)
    return files, fold


def _weekday_enabled(settings: Settings) -> bool:
    return settings.build_weekday_dataset and settings.timeframe is Timeframe.DAILY


def run_download(settings: Settings, *, show_progress: bool = True) -> int:
    started = time.monotonic()
    window_start, window_end = settings.download_window()
    years = settings.expected_years()
    log.info("Run started with %r", settings)

    if len(years) < DEFAULT_HISTORY_YEARS:
        log.warning("The configured range covers only %d calendar year(s)", len(years))

    print(
        f"Downloading {settings.display_symbol} {settings.timeframe} candles "
        f"{settings.start_date} -> {settings.end_date} from {settings.provider} ...",
        flush=True,
    )

    try:
        with closing(create_provider(settings)) as provider:
            result = ForexDownloader(provider, settings).run(show_progress=show_progress)
            provider_name = provider.display_name
    # Errors below are logged once; the console handler shows them to the user too.
    except AuthenticationError as exc:
        key = PROVIDER_API_KEY_ENV.get(settings.provider) or "the provider credentials"
        log.error("Authentication failed - check %s in your .env file. %s", key, exc)
        return EXIT_FAILED
    except (ProviderError, DownloadError) as exc:
        log.error("Download failed, nothing was saved. %s", exc)
        return EXIT_FAILED

    try:
        clean, validation = validate_ohlcv(result.data, settings.timeframe)
    except DataValidationError as exc:
        log.error("Downloaded data failed validation, nothing was saved: %s", exc)
        return EXIT_FAILED

    if clean.empty:
        log.error("No valid records were downloaded; nothing was saved. See logs/data_download.log.")
        return EXIT_FAILED

    files = write_yearly_csv(clean, settings.data_dir, settings.symbol, settings.timeframe)
    weekday_files: list[YearFile] = []
    fold: FoldReport | None = None
    if _weekday_enabled(settings):
        weekday_files, fold = build_weekday_dataset(settings, clean)

    missing_warnings = [str(gap) for gap in validation.gaps]
    written_years = {f.year for f in files}
    for year in years:
        if year not in written_years:
            message = f"No data for {year}: {yearly_filename(settings.symbol, year)} was not created"
            log.warning(message)
            missing_warnings.insert(0, message)
    if validation.null_rows_removed:
        missing_warnings.append(f"{validation.null_rows_removed} record(s) had missing values and were dropped")

    summary = DownloadSummary(
        provider=provider_name,
        symbol=settings.symbol,
        timeframe=settings.timeframe,
        requested_start=window_start.date(),
        requested_end=settings.end_date,
        data_start=clean["Date"].iloc[0],
        data_end=clean["Date"].iloc[-1],
        records_downloaded=result.records_downloaded,
        records_saved=len(clean),
        duplicates_removed=validation.duplicates_removed,
        invalid_rows_removed=validation.invalid_rows_removed,
        files=files,
        duration_seconds=time.monotonic() - started,
        failed_requests=[str(f) for f in result.failed_chunks],
        missing_data_warnings=missing_warnings,
        other_warnings=validation.warnings,
        weekday_files=weekday_files,
        fold=fold,
    )
    print()
    print(summary.render())
    report_path = save_report(summary, settings.report_dir)
    print(f"\nFull report: {report_path}")
    log.info("Run finished: %s", summary.status)
    return EXIT_OK if result.complete else EXIT_PARTIAL


def run_build_weekday(settings: Settings) -> int:
    """Rebuild the Monday-Friday dataset from daily CSV files already on disk."""
    if settings.timeframe is not Timeframe.DAILY:
        log.error("The Monday-Friday dataset only applies to daily (1d) data")
        return EXIT_CONFIG
    raw = load_yearly_csv(settings.data_dir, settings.symbol, settings.expected_years())
    if raw.empty:
        log.error("No daily CSV files found in %s; run a download first", settings.data_dir)
        return EXIT_FAILED

    clean, _ = validate_ohlcv(raw, settings.timeframe)
    raw_files = [
        YearFile(
            int(year),
            settings.data_dir / yearly_filename(settings.symbol, int(year)),
            len(group),
            group["Date"].iloc[0],
            group["Date"].iloc[-1],
        )
        for year, group in clean.groupby(clean["Date"].dt.year)
    ]
    weekday_files, fold = build_weekday_dataset(settings, clean)
    print("\n".join(render_comparison(raw_files, weekday_files, fold)))
    return EXIT_OK


def run_verify(settings: Settings) -> int:
    years = settings.expected_years()
    code = _verify_dataset(settings.data_dir, settings, years, weekdays_only=False)
    if _weekday_enabled(settings):
        print()
        code = max(code, _verify_dataset(settings.weekday_data_dir, settings, years, weekdays_only=True))
    return code


def _verify_dataset(data_dir: Path, settings: Settings, years: list[int], *, weekdays_only: bool) -> int:
    checks = verify_yearly_files(data_dir, settings.symbol, years, weekdays_only=weekdays_only)

    label = "Monday-Friday" if weekdays_only else "daily"
    print(f"Verifying {len(checks)} {label} file(s) in {data_dir}\n")
    print(f"  {'File':<18} {'Status':<6} {'Rows':>7}  {'First':<19} {'Last':<19} Problems")
    for check in checks:
        status = "OK" if check.ok else "FAIL"
        print(
            f"  {check.path.name:<18} {status:<6} {check.rows:>7,}  {check.first:<19} {check.last:<19} "
            f"{'; '.join(check.problems)}"
        )
        if not check.ok:
            log.warning("Verification failed for %s: %s", check.path, "; ".join(check.problems))

    passed = sum(c.ok for c in checks)
    total_rows = sum(c.rows for c in checks)
    print(f"\n{passed}/{len(checks)} files OK, {total_rows:,} records in total.")
    log.info("Verification: %d/%d files OK", passed, len(checks))
    return EXIT_OK if passed == len(checks) else EXIT_PARTIAL


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    overrides = {
        "DATA_PROVIDER": args.provider,
        "DATA_TIMEFRAME": args.timeframe,
        "DATA_START_DATE": args.start,
        "DATA_END_DATE": args.end,
        "LOG_LEVEL": args.log_level,
    }
    try:
        settings = load_settings(args.env_file, overrides)
        settings.download_window()  # fail early on an empty range
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    setup_logging(settings.log_dir, settings.log_level)
    try:
        if args.verify:
            return run_verify(settings)
        if args.build_weekday:
            return run_build_weekday(settings)
        return run_download(settings, show_progress=not args.no_progress)
    except KeyboardInterrupt:
        log.warning("Interrupted by user")
        print("\nInterrupted. Files already written are complete; re-run to finish.", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
