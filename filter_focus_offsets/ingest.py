"""Walk FITS trees and collect Light Focus Samples."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from astropy.io import fits

from .filters import CANONICAL, normalize_filter

LIGHT_TYPES = {"light", "light frame", "science"}
FITS_SUFFIXES = {".fit", ".fits", ".FIT", ".FITS"}


@dataclass(frozen=True)
class SetupKey:
    telescop: str
    instrume: str
    focallen: int

    def label(self) -> str:
        return f"{self.telescop} | {self.instrume} | FL={self.focallen}"


@dataclass(frozen=True)
class FocusSample:
    session_id: str
    setup: SetupKey
    filter_name: str
    focuspos: int
    binning: int
    frame_count: int = 1
    ccd_temps: tuple[float, ...] = ()


@dataclass
class IngestStats:
    files_seen: int = 0
    lights: int = 0
    with_focus: int = 0
    skipped_not_light: int = 0
    skipped_no_filter: int = 0
    skipped_no_focus: int = 0
    skipped_read_error: int = 0
    unknown_filters: set[str] = field(default_factory=set)


def _header_str(header: fits.Header, *keys: str) -> str | None:
    for key in keys:
        if key in header and header[key] is not None:
            value = str(header[key]).strip()
            if value:
                return value
    return None


def _header_float(header: fits.Header, *keys: str) -> float | None:
    for key in keys:
        if key in header and header[key] is not None:
            try:
                return float(header[key])
            except (TypeError, ValueError):
                continue
    return None


def _header_int(header: fits.Header, *keys: str) -> int | None:
    value = _header_float(header, *keys)
    if value is None:
        return None
    return int(round(value))


def _is_light(imagetyp: str | None) -> bool:
    if imagetyp is None:
        return False
    return imagetyp.strip().lower() in LIGHT_TYPES


def _normalize_focallen(focallen: int) -> int:
    """Collapse ASIAIR FL jitter (±3) into the nearest common Setup length."""
    if focallen <= 0:
        return focallen
    # Observed clusters: ~249 (RC/short) and ~500 (FRA)
    for center in (249, 500):
        if abs(focallen - center) <= 3:
            return center
    return focallen


def _session_id(path: Path, root: Path) -> str:
    """Session = parent folder of the FITS file, relative to scan root when possible."""
    parent = path.parent.resolve()
    try:
        rel = parent.relative_to(root.resolve())
        return str(rel)
    except ValueError:
        return str(parent)


def discover_fits(roots: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        root = root.expanduser().resolve()
        if not root.exists():
            continue
        if root.is_file() and root.suffix in FITS_SUFFIXES:
            files.append(root)
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in FITS_SUFFIXES:
                # skip vendored software test fixtures
                parts = {p.lower() for p in path.parts}
                if "software" in parts and "tests" in parts:
                    continue
                if "_internal" in parts:
                    continue
                files.append(path)
    return sorted(files)


def ingest_lights(roots: Iterable[Path]) -> tuple[list[FocusSample], IngestStats]:
    """Return unique Focus Samples (Session, Filter, FOCUSPOS) and ingest stats."""
    stats = IngestStats()
    # key -> accumulator
    buckets: dict[tuple, dict] = {}
    root_list = [Path(r).expanduser().resolve() for r in roots]

    for root in root_list:
        for path in discover_fits([root]):
            stats.files_seen += 1
            try:
                with fits.open(path, memmap=False) as hdul:
                    header = hdul[0].header
            except Exception:
                stats.skipped_read_error += 1
                continue

            imagetyp = _header_str(header, "IMAGETYP", "IMAGETYPE", "FRAME")
            # Filename fallback for ASIAIR when header missing (rare)
            if imagetyp is None and path.name.lower().startswith("light"):
                imagetyp = "Light"
            if not _is_light(imagetyp):
                stats.skipped_not_light += 1
                continue
            stats.lights += 1

            raw_filter = _header_str(header, "FILTER")
            filter_name = normalize_filter(raw_filter)
            if not filter_name:
                stats.skipped_no_filter += 1
                continue
            if filter_name not in CANONICAL:
                stats.unknown_filters.add(filter_name)

            focuspos = _header_int(header, "FOCUSPOS", "FOCPOS", "ABSFOCUSPOS")
            if focuspos is None:
                stats.skipped_no_focus += 1
                continue
            stats.with_focus += 1

            telescop = _header_str(header, "TELESCOP") or "UNKNOWN"
            instrume = _header_str(header, "INSTRUME") or "UNKNOWN"
            focallen = _header_int(header, "FOCALLEN") or 0
            focallen = _normalize_focallen(focallen)
            setup = SetupKey(telescop=telescop, instrume=instrume, focallen=focallen)

            binning = _header_int(header, "XBINNING", "CCDXBIN") or 1
            session_id = _session_id(path, root)
            ccd_temp = _header_float(header, "CCD-TEMP")

            key = (session_id, setup, filter_name, focuspos, binning)
            bucket = buckets.get(key)
            if bucket is None:
                buckets[key] = {
                    "frame_count": 1,
                    "temps": [ccd_temp] if ccd_temp is not None else [],
                }
            else:
                bucket["frame_count"] += 1
                if ccd_temp is not None:
                    bucket["temps"].append(ccd_temp)

    samples: list[FocusSample] = []
    for (session_id, setup, filter_name, focuspos, binning), bucket in buckets.items():
        samples.append(
            FocusSample(
                session_id=session_id,
                setup=setup,
                filter_name=filter_name,
                focuspos=focuspos,
                binning=binning,
                frame_count=bucket["frame_count"],
                ccd_temps=tuple(bucket["temps"]),
            )
        )
    samples.sort(key=lambda s: (s.setup.label(), s.session_id, s.filter_name, s.focuspos))
    return samples, stats


def group_by_setup(
    samples: list[FocusSample],
) -> dict[SetupKey, list[FocusSample]]:
    grouped: dict[SetupKey, list[FocusSample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.setup].append(sample)
    return dict(grouped)
