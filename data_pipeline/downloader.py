"""Download orchestration: runs a provider over the configured date range."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

from data_pipeline.config import Settings
from data_pipeline.progress import ProgressBar
from data_pipeline.providers.base import (
    OHLCV_COLUMNS,
    AuthenticationError,
    BaseProvider,
    Chunk,
    ProviderError,
    RateLimitError,
    empty_ohlcv,
)

log = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    """The download produced no usable data at all."""


@dataclass(frozen=True, slots=True)
class FailedChunk:
    chunk: Chunk
    reason: str

    def __str__(self) -> str:
        return f"{self.chunk.label}: {self.reason}"


@dataclass
class DownloadResult:
    """Raw (not yet validated) data plus bookkeeping about the run."""

    data: pd.DataFrame
    chunks_total: int
    records_downloaded: int
    failed_chunks: list[FailedChunk] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.failed_chunks


class ForexDownloader:
    """Fetches every chunk of the configured window from one provider.

    A failed chunk is logged and skipped so a single bad request does not lose the
    rest of the run. Authentication errors abort immediately, because every
    further request would fail the same way. A rate limit that survives all
    retries stops the run early but keeps the data downloaded so far.
    """

    def __init__(self, provider: BaseProvider, settings: Settings) -> None:
        self.provider = provider
        self.settings = settings

    def run(self, *, show_progress: bool = True) -> DownloadResult:
        start, end = self.settings.download_window()
        chunks = self.provider.plan_chunks(start, end)
        log.info(
            "Downloading %s %s candles from %s via %s: %s -> %s UTC (%d request batch(es))",
            self.settings.display_symbol, self.settings.timeframe, start.date(),
            self.provider.display_name, start, end, len(chunks),
        )

        frames: list[pd.DataFrame] = []
        failed: list[FailedChunk] = []
        records = 0

        progress = ProgressBar(
            len(chunks), f"{self.provider.display_name} {self.settings.display_symbol}"
        ) if show_progress else None
        try:
            for index, chunk in enumerate(chunks):
                try:
                    frame = self.provider.fetch_chunk(chunk)
                except AuthenticationError:
                    raise
                except RateLimitError as exc:
                    remaining = chunks[index:]
                    log.error(
                        "Rate limit persisted after retries at %s; stopping early (%d remaining batch(es) skipped): %s",
                        chunk.label, len(remaining) - 1, exc,
                    )
                    failed.append(FailedChunk(chunk, str(exc)))
                    failed.extend(FailedChunk(c, "skipped: provider rate limit") for c in remaining[1:])
                    if progress:
                        progress.update(len(remaining), status="stopped: rate limited")
                    break
                except ProviderError as exc:
                    log.error("Download failed for %s: %s", chunk.label, exc)
                    failed.append(FailedChunk(chunk, str(exc)))
                except Exception as exc:  # unexpected parsing/runtime bug: log it, keep going
                    log.exception("Unexpected error while downloading %s", chunk.label)
                    failed.append(FailedChunk(chunk, f"{type(exc).__name__}: {exc}"))
                else:
                    frame = _clip_to_chunk(frame, chunk)
                    records += len(frame)
                    if frame.empty:
                        log.warning("No data returned for %s", chunk.label)
                    else:
                        log.info("Downloaded %d record(s) for %s", len(frame), chunk.label)
                        frames.append(frame)

                if progress:
                    progress.update(status=f"{chunk.label} | {records:,} records")
        finally:
            if progress:
                progress.close()

        if chunks and len(failed) == len(chunks):
            raise DownloadError(
                f"All {len(chunks)} request batch(es) to {self.provider.display_name} failed. "
                f"First error: {failed[0].reason}"
            )

        data = pd.concat(frames, ignore_index=True) if frames else empty_ohlcv()
        log.info("Download finished: %d record(s), %d failed batch(es)", records, len(failed))
        return DownloadResult(data=data, chunks_total=len(chunks), records_downloaded=records, failed_chunks=failed)


def _clip_to_chunk(frame: pd.DataFrame, chunk: Chunk) -> pd.DataFrame:
    """Keep rows inside ``[chunk.start, chunk.end)``.

    Rows whose date cannot be parsed are kept so the validator can count and report them.
    """
    if frame.empty:
        return frame
    frame = frame.loc[:, OHLCV_COLUMNS].copy()
    dates = pd.to_datetime(frame["Date"], utc=True, errors="coerce", format="mixed")
    inside = (dates >= pd.Timestamp(chunk.start)) & (dates < pd.Timestamp(chunk.end))
    frame["Date"] = dates
    return frame.loc[inside | dates.isna()].reset_index(drop=True)
