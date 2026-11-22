"""End-to-end run of the CLI with a simulated provider (no network access)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_pipeline import main as cli
from data_pipeline.providers.base import BaseProvider, Chunk


class SimulatedProvider(BaseProvider):
    """Returns synthetic weekday candles, plus one duplicate and one bad row per chunk."""

    name = "simulated"
    display_name = "Simulated"

    def fetch_chunk(self, chunk: Chunk) -> pd.DataFrame:
        days = pd.bdate_range(chunk.start, chunk.end, inclusive="left")
        days = days[~((days.month == 12) & (days.day == 25)) & ~((days.month == 1) & (days.day == 1))]
        rng = np.random.default_rng(chunk.start.year)
        close = 1.10 + rng.normal(0, 0.002, len(days)).cumsum()
        df = pd.DataFrame(
            {"Date": days, "Open": close, "High": close + 0.003, "Low": close - 0.003, "Close": close, "Volume": 1000.0}
        )
        bad = df.iloc[[0]].assign(High=0.5)  # High < Low -> must be removed
        return pd.concat([df, df.iloc[[1]], bad], ignore_index=True)


def test_full_download_creates_yearly_files_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DATA_PROVIDER=dukascopy\n", encoding="utf-8")
    for name, sub in (
        ("DATA_DIR", "data"), ("WEEKDAY_DATA_DIR", "data/weekday"), ("LOG_DIR", "logs"), ("REPORT_DIR", "reports"),
    ):
        monkeypatch.setenv(name, str(tmp_path / sub))
    monkeypatch.setattr(cli, "create_provider", lambda settings: SimulatedProvider(settings))

    args = ["--env-file", str(env_file), "--start", "2016-01-01", "--end", "2026-11-20", "--no-progress"]
    assert cli.main(args) == cli.EXIT_OK

    files = sorted(p.name for p in (tmp_path / "data").glob("*.csv"))
    assert files == [f"EURUSD_{year}.csv" for year in range(2016, 2027)]

    output = capsys.readouterr().out
    assert "Total Files Created       : 11" in output
    assert "Start Date                : 2016-01-01" in output or "Start Date                : 2016-01-04" in output
    assert "Duplicates Removed        : 11" in output
    assert "Invalid Rows Removed      : 11" in output
    assert list((tmp_path / "reports").glob("EURUSD_download_summary_*.txt"))
    assert (tmp_path / "logs" / "data_download.log").stat().st_size > 0

    weekday = sorted(p.name for p in (tmp_path / "data" / "weekday").glob("*.csv"))
    assert weekday == files
    assert "Monday-Friday dataset" in output

    assert cli.main([*args[:-1], "--verify"]) == cli.EXIT_OK
    assert capsys.readouterr().out.count("11/11 files OK") == 2  # daily + Monday-Friday

    assert cli.main([*args[:-1], "--build-weekday"]) == cli.EXIT_OK
    assert "Sunday candles folded" in capsys.readouterr().out
