2026-03-29: Source data is `/Users/wxmiked/Downloads/fire23_1.gdb` (layer `firep23_1`, CAL FIRE statewide fire perimeters).

Original CAL FIRE source pages:
- [CAL FIRE FRAP Fire Perimeters](https://www.fire.ca.gov/what-we-do/fire-resource-assessment-program/fire-perimeters)

Direct CAL FIRE GDB download link used:
- [CAL FIRE 2025 Fire Perimeters Geodatabase (direct download)](https://34c031f8-c9fd-4018-8c5a-4159cdff6b0d-cdn-endpoint.azureedge.net/-/media/calfire-website/what-we-do/fire-resource-assessment-program---frap/gis-data/2025/fire241gdb.ash'?rev=51177a999fe84e83a7c03b7d5a66b93b)

Extracted the single Amador/Calaveras Butte Fire perimeter (`OBJECTID = 3188`) into `butte-fire.geojson` with:

```bash
mkdir -p /Users/wxmiked/vscode-workspace/cannabis/cannabis-deforestation/data-to-import/calfire && ogr2ogr -f GeoJSON /Users/wxmiked/vscode-workspace/cannabis/cannabis-deforestation/data-to-import/calfire/butte-fire.geojson /Users/wxmiked/Downloads/fire23_1.gdb firep23_1 -where "OBJECTID = 3188" -t_srs EPSG:4326 -nln butte_fire
```

Verification command:

```bash
ogrinfo -so /Users/wxmiked/vscode-workspace/cannabis/cannabis-deforestation/data-to-import/calfire/butte-fire.geojson butte_fire
```
