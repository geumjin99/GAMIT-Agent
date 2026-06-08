# Sample data

`korea_doy200_2023.zip` — a small four-station sample for the worked example in the
[User Manual](../docs/USER_MANUAL.md#5-worked-example).

| Field | Value |
|---|---|
| Network | 4 stations: **DAEJ, INCH, SKMA, SONP** (Republic of Korea; DAEJ is an IGS site) |
| Epoch | Year **2023**, day-of-year **200** (2023-07-19, GPS week 2271) |
| `_INBOX_korea_200/` | Bare RINEX 2 observation (`*.23o`) and broadcast navigation (`*.23n`) files — **the Browse target** |
| `orbits/` | IGS products for an **offline** (`-noftp`) run: `igs22713.sp3` (precise orbit), `gigsg3.200` (g-file), `brdc2000.23n` (merged broadcast ephemeris) |
| Size | ~25 MB uncompressed / ~7.6 MB zipped |

EOP tables (`pole.usno`, `ut1.usno`) are **not** bundled; they ship with your GAMIT
installation under `tables/`.

## Usage

```bash
unzip korea_doy200_2023.zip -d ./sample_run
```

- **Online (default):** Browse to `sample_run/_INBOX_korea_200`, build the project, and run;
  `sh_gamit` downloads the IGS orbit/EOP automatically.
- **Offline:** after building the project, copy `sample_run/orbits/igs22713.sp3` into the
  project's `igs/` folder (and `gigsg3.200` into `gfiles/`), then run with the `-noftp` option.

See the [worked example](../docs/USER_MANUAL.md#5-worked-example) for the expected output.

These are publicly available GNSS observations and IGS products, redistributed here only as a
minimal reproducibility sample.
