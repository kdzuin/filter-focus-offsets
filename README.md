# filter-focus-offsets

Estimate **filter focus offsets** from ASIAIR Light FITS frames.

The tool walks one or more directories, keeps Light frames with `FILTER` + `FOCUSPOS`, groups them into **Sessions** (folders) and **Setups** (telescope + camera + focal length), then:

1. Builds **Focus Samples** (unique focuser positions — frame count is not confidence)
2. Detects optical **Configurations** when absolute `FOCUSPOS` jumps (e.g. CAA / backfocus change)
3. Rejects outliers outside ±Nσ via **MAD** (median absolute deviation; default 3) — resistant to a single bad night inflating σ
4. Reports per-Session offsets, cross-Session edge confidence, and an optional **Setup Offset Set** with **L = 0**

Designed for claimed-parfocal filter kits (Antlia V-Pro LRGB + Antlia 3nm NB). It will refuse to “publish” a single ASIAIR offset table when the data does not support one.

Domain vocabulary: see [GLOSSARY.md](GLOSSARY.md).

## Requirements

- Python 3.9+
- `astropy`, `numpy`

## Install

```bash
git clone https://github.com/<you>/filter-focus-offsets.git
cd filter-focus-offsets
python3 -m pip install -e .
```

Or run without installing:

```bash
PYTHONPATH=. python3 -m filter_focus_offsets /path/to/fits
```

## Usage

```bash
# Text report on stdout
filter-focus-offsets ~/Astro/Projects

# HTML report (self-contained)
filter-focus-offsets ~/Astro/Projects --html report.html

# HTML only
filter-focus-offsets ~/Astro/Projects --quiet --html report.html
```

### Useful flags

| Flag | Default | Meaning |
|------|---------|---------|
| `--af-step` | `30` | ASIAIR AF coarse step (for context / gates) |
| `--agree-tol` | `10` | Max spread for a cross-Session edge to count as confident |
| `--accept-error` | `15` | Parfocal / “good enough to skip AF” band (~½ AF step) |
| `--outlier-sigma` | `3` | Drop FOCUSPOS outside ±Nσ (MAD-based); `0` disables |
| `--config-gap` | `2500` | Absolute FOCUSPOS gap that starts a new Configuration |
| `--allow-no-l` | off | Allow publishing without Luminance in the graph |
| `--html PATH` | — | Write HTML report |
| `--quiet` | off | Skip text report |

Exit codes: `0` all Configurations publishable, `1` no usable Focus Samples, `2` at least one Configuration not publishable.

## What it assumes

- ASIAIR (or compatible) Lights with `IMAGETYP=Light`, `FILTER`, `FOCUSPOS`
- AF usually run on filter change, so Lights sit near best focus per filter
- Filter names normalize to: **L R G B SII Ha OIII** (including short ASIAIR names `H`/`O`/`S`)
- Focal length jitter of ±3 mm is clustered (e.g. 499 → 500)

## Output

- **Per-Session offsets** — primary, trustworthy within a night
- **Offset edges** — filter−filter deltas across Sessions, with confidence
- **Setup Offset Set** — L-relative vector for L-bridged filters only; publish gate may refuse
- **HTML** — TOC of Setups/Configurations, charts of FOCUSPOS over Sessions, tables

## Status

Prototype (`0.1.0`). Works on real ASIAIR archives; publish gates are intentionally conservative for claimed-parfocal kits.

## License

TBD — add a `LICENSE` before publishing (e.g. MIT).
