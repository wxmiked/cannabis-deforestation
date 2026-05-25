import json
import tempfile
import unittest
from pathlib import Path

from cannabis_deforestation.county_inference import (
    build_manifest,
    county_boundary_from_kml,
    main,
)


class CountyInferencePlanningTests(unittest.TestCase):
    def test_county_boundary_from_kml_extracts_bbox(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            kml_path = Path(tmpdir) / "county.kml"
            kml_path.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              -120.0,38.0,0 -121.0,38.5,0 -120.5,37.5,0 -120.0,38.0,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>
""",
                encoding="utf-8",
            )

            county = county_boundary_from_kml(kml_path)

        self.assertEqual(county.coordinate_count, 4)
        self.assertEqual(county.bbox_wgs84, [-121.0, 37.5, -120.0, 38.5])

    def test_build_manifest_creates_one_shard_per_stac_item(self):
        county = county_boundary_from_kml(
            Path("data-to-import/calaveras-county/boundary/COUNTY_BOUNDARY.kml")
        )
        items = [
            {
                "id": "ca_m_3812040_nw_10_.6_20160802_20161004",
                "bbox": [-120.8, 38.0, -120.7, 38.1],
                "geometry": {"type": "Polygon"},
                "properties": {"datetime": "2016-08-02T00:00:00Z"},
                "assets": {"image": {"href": "https://example.test/naip-one.tif"}},
            },
            {
                "id": "ca_m_3812040_ne_10_.6_20160802_20161004",
                "bbox": [-120.7, 38.0, -120.6, 38.1],
                "geometry": {"type": "Polygon"},
                "properties": {"datetime": "2016-08-02T00:00:00Z"},
                "assets": {"image": {"href": "https://example.test/naip-two.tif"}},
            },
        ]

        manifest = build_manifest(
            year=2016,
            county=county,
            stac_items=items,
            asset_key="image",
            source="test-fixture",
        )

        self.assertEqual(manifest["year"], 2016)
        self.assertEqual(manifest["stac"]["item_count"], 2)
        self.assertEqual(manifest["shards"][0]["shard_id"], 0)
        self.assertEqual(manifest["shards"][1]["shard_id"], 1)
        self.assertEqual(
            manifest["shards"][0]["asset_href"], "https://example.test/naip-one.tif"
        )

    def test_cli_plan_county_uses_stac_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fixture = tmp_path / "items.json"
            out = tmp_path / "manifest.json"
            fixture.write_text(
                json.dumps(
                    {
                        "features": [
                            {
                                "id": "test-item",
                                "bbox": [-120.8, 38.0, -120.7, 38.1],
                                "geometry": {"type": "Polygon"},
                                "properties": {},
                                "assets": {
                                    "image": {"href": "https://example.test/test.tif"}
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "plan-county",
                    "--year",
                    "2016",
                    "--county",
                    "data-to-import/calaveras-county/boundary/COUNTY_BOUNDARY.kml",
                    "--stac-items-json",
                    str(fixture),
                    "--out",
                    str(out),
                ]
            )

            manifest = json.loads(out.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(manifest["stac"]["item_count"], 1)
        self.assertEqual(manifest["shards"][0]["naip_item_id"], "test-item")


if __name__ == "__main__":
    unittest.main()

