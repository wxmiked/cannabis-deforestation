# DWR Statewide Crop Mapping 2016 — Source Documentation

Downloaded: 2026-05-19  
Prepared by: Land IQ LLC, reviewed/revised by DWR Regional Office staff

## Data Source

**California DWR Statewide Crop Mapping, 2016**
- Dataset page: https://data.cnra.ca.gov/dataset/statewide-crop-mapping
- Direct download (2016 GDB zip):
  https://data.cnra.ca.gov/dataset/6c3d65e3-35bb-49e1-a51e-49d5a2cf09a9/resource/489d7ab8-f68a-45b4-8113-bb89bc4d9a9c/download/i15_crop_mapping_2016_gdb.zip
- DWR land use legend (2022, applies to 2016+ datasets):
  https://water.ca.gov/-/media/DWR-Website/Web-Pages/Programs/Water-Use-And-Efficiency/Land-And-Water-Use/Land-Use-Surveys/Files/2022-standard-land-use-legend-remote-sensing_ADA-compliant.pdf

## Download Command

```bash
curl -L -o data-to-import/dwr-crop-mapping-2016/i15_crop_mapping_2016_gdb.zip \
  "https://data.cnra.ca.gov/dataset/6c3d65e3-35bb-49e1-a51e-49d5a2cf09a9/resource/489d7ab8-f68a-45b4-8113-bb89bc4d9a9c/download/i15_crop_mapping_2016_gdb.zip"
unzip i15_crop_mapping_2016_gdb.zip -d data-to-import/dwr-crop-mapping-2016/
```

The zip file (83 MB) and extracted GDB are excluded from git. See `.gitignore`.

## Schema (confirmed via fiona inspection, 2026-05-19)

**Layer name:** `i15_Crop_Mapping_2016`  
**Source CRS:** EPSG:3857 (Web Mercator) — NOT EPSG:3310 as sometimes documented  
**Total features (statewide):** 390,666  
**Calaveras County features:** 483

Key fields:

| Field | Type | Notes |
|-------|------|-------|
| `Symb_class` | str:4 | Primary land use class code. Use this for filtering — `CLASS2` has leading spaces. |
| `CLASS2` | str:2 | Same info as Symb_class but with leading space padding (e.g., `' D'`). |
| `County` | str:50 | Full county name (e.g., `'Calaveras'`). Not a FIPS code. |
| `Crop2016` | str:50 | Human-readable crop label (e.g., `'Grapes'`, `'Walnuts'`). Useful for verification. |
| `Acres` | float | Polygon area in acres. |
| `SUBCLASS2` | str:2 | Subclass code (e.g., `'12'` for Almonds within `D`). |

## Calaveras County 2016 — Class Distribution

| Symb_class | Crop2016 (examples) | Count | Masked? |
|------------|---------------------|-------|---------|
| V | Grapes | 210 | YES |
| P | Mixed Pasture | 75 | YES |
| D | Walnuts, Olives (via C), Almonds, Pistachios... | 67 | YES |
| C | Olives | 59 | YES |
| X | Idle / Unclassified Fallow | 50 | NO — cannabis grows observed here |
| YP | Young Perennials | 12 | YES |
| T | Miscellaneous Truck Crops | 7 | NO — T16 includes cannabis |
| G | Miscellaneous Grain and Hay | 3 | YES |

**Mask output:** 426 features (V+P+D+C+YP+G)  
**Excluded from mask:** 57 features (X=50, T=7)

Note: One `D`-class parcel has `Crop2016='Idle'` (an orchard that was temporarily
idle during the 2016 survey). It is correctly included in the mask since the land
classification is still deciduous orchard, which presents FP NIR signatures.

## Mask Extraction Command

```bash
python scripts/build_dwr_crop_mask.py \
    --gdb data-to-import/dwr-crop-mapping-2016/i15_Crop_Mapping_2016_GDB/i15_Crop_Mapping_2016.gdb \
    --county Calaveras \
    --out data-to-import/dwr-crop-mapping-2016/calaveras_crop_mask_2016.geojson
```

Dependencies: `pip install fiona shapely pyproj`

## Output File

`calaveras_crop_mask_2016.geojson` — 426 features, EPSG:4326  
Committed to git (small enough; ~600KB).

## Notes on CLASS2 vs Symb_class

`CLASS2` stores values with a leading space (e.g., `' D'`, `' V'`), while `Symb_class`
is clean (e.g., `'D'`, `'V'`). Always use `Symb_class` for programmatic filtering
to avoid whitespace bugs.

The `F` class (Field Crops: cotton, corn, sugar beets, etc.) is distinct from
fallow suffixes like `-F` appended to other class codes (e.g., `T-F`, `G-F`).
Neither `F` nor the `X`/`I` fallow classes are present in Calaveras 2016, but
the script correctly handles them for other counties/years.
