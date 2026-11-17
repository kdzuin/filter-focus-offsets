# Filter Focus Offsets

Domain language for estimating ASIAIR filter focus offsets from Light FITS frames.

## Language

**Setup**:
A fixed telescope + camera + focal-length combination, identified from FITS headers (`TELESCOP`, `INSTRUME`, `FOCALLEN`).
_Avoid_: profile, equipment set, rig (unless speaking casually)

**Configuration**:
An optical-train state within a Setup, detected by a large gap in absolute FOCUSPOS across Sessions (e.g. CAA / backfocus change). Filter offsets are estimated per Configuration.
_Avoid_: Setup (broader), Session (narrower)

**Session**:
One folder of Lights that share the same Setup fingerprint and binning; the unit within which filter focus positions are comparable.
_Avoid_: night, run (a calendar night may contain multiple Sessions)

**Light**:
A science exposure frame with `IMAGETYP=Light` (or equivalent).
_Avoid_: subframe, sub (unless counting)

**Focus Sample**:
One `(Session, Filter, FOCUSPOS)` observation. Many Lights at the same focuser position still count as one sample.
_Avoid_: frame average, weighted median of all frames

**Offset Edge**:
The focuser-step difference between two Filters measured inside the same Session.
_Avoid_: absolute focus, FOCUSPOS (those are positions, not edges)

**Setup Offset Set**:
One vector of filter offsets for a Setup, published with Luminance at zero when L is in the graph.
_Avoid_: per-night offsets, AF table (unless referring to ASIAIR UI)

**Filter Kit**:
A claimed-parfocal group of Filters: Antlia V-Pro LRGB, or Antlia 3nm narrowband (SII/Ha/OIII).
_Avoid_: filter wheel, band set

**Reference Filter**:
The gauge filter for a published Setup Offset Set; Luminance (`L`) when present in the graph.
_Avoid_: master filter, base filter
