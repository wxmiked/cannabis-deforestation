# Cannabis Parcels

This directory contains GIS data and parcel records for cannabis cultivation sites in Calaveras County, California, derived from the county's 2016 Urgency Ordinance permit registry.

## Extracting parcel numbers from the permit registry

The Calaveras County Planning Department provided a PDF version of a spreadsheet containing the parcel numbers of all parcels that applied for cannabis cultivation permits ([reports/calaveras-county-civil-grand-jury-2022-2023-cannabis-report.pdf](../reports/calaveras-county-civil-grand-jury-2022-2023-cannabis-report.pdf)).

The parcel numbers were extracted to a CSV from the PDF using the following command:

```
echo apn > cannabis-parcels/cannabis-registry-2018-commercial-apns.csv
pdftotext -layout -nopgbrk data-to-import/calaveras-county/public-record-cannabis-cultivation-database-2018-02.pdf - | grep COMMERCIAL | gsed -e 's#.*\([0-9]\{8\}\).*#\1#g' | egrep '^[0-9]{8}' >> cannabis-parcels/cannabis-registry-2018-commercial-apns.csv
```

## Extracting GIS data from county parcel boundaries

The parcel numbers were used to extract spatial data from the Calaveras County Parcel GIS dataset.

Steps:

1. Create a SQLite database to store the cannabis cultivation sites parcel numbers.
    ```
    ogr2ogr -f "SQLite" cannabis-parcels/cannabis-registry.sqlite cannabis-parcels/cannabis-registry-2018-commercial-apns.csv -nln cannabis_registry
    ```
2. Create a [VRT file](https://gdal.org/drivers/vector/vrt.html) to extract the GIS data from the Calaveras County Parcel GIS data. See [parcels.vrt](./parcels.vrt) for the VRT file used.
3. Run the OGR command to extract the GIS data from the Calaveras County Parcel GIS data.
    ```
    # Only extract parcels with cannabis permits (reduces file size from ~200MB to ~3MB)
    ogr2ogr -f "GPKG" cannabis-parcels/cannabis-registry-2018-commercial-permits-parcels.gpkg \
    cannabis-parcels/parcels.vrt \
    -sql "SELECT p.* FROM parcels p INNER JOIN cannabis_registry c ON p.APN = c.apn" \
    -dialect SQLite
    ```

    **Note:** The original command used `LEFT JOIN` which included all 43,476 county parcels. Using `INNER JOIN` filters to only the ~712 parcels with cannabis permits, reducing file size by ~98%.

## Extracting NAIP imagery for parcels

The parcel numbers were used to extract NAIP imagery tiles for each permitted parcel. See [parcels.vrt](./parcels.vrt) for the VRT file used.

For the full imagery extraction workflow, see [`notebooks/02-create-cannabis-parcel-images.ipynb`](../notebooks/02-create-cannabis-parcel-images.ipynb).

## Annotating training data with LabelMe

After extracting NAIP imagery tiles from permitted parcels, the images were manually annotated using [LabelMe](https://github.com/wkentaro/labelme) to create ground truth labels for training the semantic segmentation model.

### Installing LabelMe

```bash
pip install labelme
```

### Annotation workflow

1. **Launch LabelMe** with the directory containing extracted NAIP tiles:
   ```bash
   labelme cannabis-parcels/cannabis-parcels-masked/
   ```

2. **Create polygon annotations** by clicking points around cultivation sites. LabelMe will save a JSON file for each annotated image.

3. **Use the following labels**:
   - `cannabis` - Open-air cannabis cultivation sites (rows of plants, cleared areas with visible cultivation)
   - `hoop house - old` - Greenhouse/hoop house structures used for cultivation
   - `cannabis - old` - Abandoned or inactive cultivation sites (excluded from training)

4. **Annotation tips**:
   - Draw tight polygons around visible cultivation areas
   - Include multiple polygons per image if there are multiple distinct grow sites
   - Be consistent with polygon boundaries
   - Skip images with no visible cultivation (these become negative examples)

### Output format

LabelMe creates a JSON file for each annotated image containing polygon coordinates in pixel space, label names, and image metadata.

Example structure:
```json
{
  "version": "5.8.1",
  "shapes": [
    {
      "label": "cannabis",
      "points": [[x1, y1], [x2, y2], ...],
      "shape_type": "polygon"
    }
  ],
  "imagePath": "10019035_20160620.tif",
  "imageHeight": 1133,
  "imageWidth": 979
}
```

The training code in [`notebooks/03-cannabis-segmentation-torchgeo.ipynb`](../notebooks/03-cannabis-segmentation-torchgeo.ipynb) reads these JSON files and converts the pixel-space polygons to georeferenced masks using the image's geospatial transform.
