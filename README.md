# cannabis-deforestation

## Introduction

The cultivation of cannabis has been linked to deforestation, particularly in regions where illegal or unregulated farming practices prevail. This repository aims to investigate the environmental impact of cannabis cultivation on forested areas, with a focus on analyzing data from sources such as the National Agriculture Imagery Program (NAIP) and records from Calaveras County. By leveraging geospatial imagery and public records, we seek to identify patterns and assess the extent to which cannabis farming contributes to deforestation. Our goal is to provide insights that can inform sustainable agricultural practices and policy decisions.

This repository is a work in progress. See the [wiki](https://github.com/wxmiked/cannabis-deforestation/wiki) for more information.

## Cannabis legalization in Calaveras County

The history of cannabis legalization in Calaveras County, as detailed in the [2023 Calaveras County Civil Grand Jury Report](reports/calaveras-county-civil-grand-jury-2022-2023-cannabis-report.pdf), highlights a complex and evolving regulatory landscape. Following the statewide legalization of recreational cannabis through Proposition 64 in 2016, the county introduced an Urgency Ordinance to regulate and tax cannabis cultivation. This ordinance required applicants to already be growing cannabis before applying for permits, which led to an increase in unregistered cultivation sites when applications were denied.

In 2018, the Calaveras County Board of Supervisors banned all commercial cannabis cultivation, making previously permitted sites illegal. According to the grand jury report, this decision caused some growers to leave the legal market, while others turned to illegal operations. In 2019, the county established the Division of Cannabis Control to oversee permitting, but the report highlights continued issues with disjointed enforcement, inadequate environmental monitoring, and weak penalties for violations.

The grand jury found that illegal cannabis cultivation has significantly impacted the environment, including deforestation, soil and water contamination, and overuse of groundwater. However, environmental damage often goes unaddressed due to limited coordination among county agencies, insufficient resources for remediation, and a lack of environmental testing at cultivation sites. By 2022, there were 65 licensed cultivation sites, but the number of illegal operations far exceeded this figure.

This summary is based entirely on findings from the Calaveras County Civil Grand Jury Report published in June 2023, which examined the county's efforts to regulate cannabis and the resulting environmental consequences.

## Creating a map of cannabis cultivation sites

To create a geospatial dataset of parcels engaged in cannabis farming under Calaveras County's 2016 Urgency Ordinance, we used publicly available permit data and geographic records ([details at the repo wiki](https://github.com/wxmiked/cannabis-deforestation/wiki)). The dataset includes all parcels that applied for cannabis cultivation permits as required by the ordinance, which mandated proof of active cultivation at the time of application. Parcel boundaries and property ownership information were cross-referenced with county parcel GIS data. This dataset provides a foundation for studying the environmental impacts of cannabis cultivation, including deforestation and resource use, in Calaveras County.

### Extracting cannabis cultivation sites parcel numbers

The Calaveras County Planning Department provided a PDF version of a spreadsheet containing the parcel numbers of all parcels that applied for cannabis cultivation permits ([reports/calaveras-county-civil-grand-jury-2022-2023-cannabis-report.pdf](reports/calaveras-county-civil-grand-jury-2022-2023-cannabis-report.pdf)).

The parcel numbers were extracted to a CSV from the PDF using the following command:
```
echo apn > cannabis-parcels/cannabis-registry-2018-commercial-apns.csv
pdftotext -layout -nopgbrk data-to-import/calaveras-county/public-record-cannabis-cultivation-database-2018-02.pdf - | grep COMMERCIAL | gsed -e 's#.*\([0-9]\{8\}\).*#\1#g' | egrep '^[0-9]{8}' >> cannabis-parcels/cannabis-registry-2018-commercial-apns.csv
```

### Using the cannabis cultivation sites parcel numbers to extract GIS data

The parcel numbers were then used to extract the GIS data from the Calaveras County Parcel GIS data.

Steps:
1. Create a SQLite database to store the cannabis cultivation sites parcel numbers.
    ```
    ogr2ogr -f "SQLite" cannabis-parcels/cannabis-registry.sqlite cannabis-parcels/cannabis-registry-2018-commercial-apns.csv -nln cannabis_registry
    ```
2. Create a [VRT file](https://gdal.org/drivers/vector/vrt.html
) to extract the GIS data from the Calaveras County Parcel GIS data. See [parcels.vrt](./cannabis-parcels/parcels.vrt) for the VRT file used.
3. Run the OGR command to extract the GIS data from the Calaveras County Parcel GIS data.
    ```
    ogr2ogr -f "ESRI Shapefile" cannabis-parcels/cannabis-registry-2018-commercial-apns.shp \
    cannabis-parcels/parcels.vrt \
    -sql "SELECT p.* FROM parcels p JOIN cannabis_registry c ON p.APN = c.apn" \
    -dialect SQLite
    ```
4. Create a Shapefile of the non-cannabis parcels.
    ```
    ogr2ogr -f "ESRI Shapefile" cannabis-parcels/non-cannabis-parcels.shp \
    cannabis-parcels/parcels.vrt \
    -sql "SELECT p.* FROM parcels p WHERE p.APN NOT IN (SELECT apn FROM cannabis_registry)" \
    -dialect SQLite
    ```

### Using the cannabis cultivation sites parcel numbers to extract NAIP imagery

The parcel numbers were then used to extract the NAIP imagery from the Calaveras County Parcel GIS data.

Steps:
1. Create a VRT file to extract the NAIP imagery from the Calaveras County Parcel GIS data. See [parcels.vrt](./cannabis-parcels/parcels.vrt) for the VRT file used.
