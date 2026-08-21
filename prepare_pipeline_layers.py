from pathlib import Path

import geopandas as gpd
import pandas as pd


PROJECT_ROOT = Path("/Users/willgirling/Desktop/NGTL Project")

PIPELINE_FILE = (
    PROJECT_ROOT
    / "Pipelines_SHP"
    / "Pipelines_GCS_NAD83.shp"
)

OUTPUT_DIR = PROJECT_ROOT / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    columns = [
        "LICENCE_NO",
        "LINE_NO",
        "LIC_LI_NO",
        "PLLICSEGID",
        "COMP_NAME",
        "BA_CODE",
        "SEG_LENGTH",
        "SEG_STATUS",
        "FROM_FAC",
        "TO_FAC",
        "OUT_DIAMET",
        "PIPE_MAOP",
        "BIDIRE_IND",
        "SUBSTANCE1",
        "SUBSTANCE2",
        "SUBSTANCE3",
        "GEOM_SRCE",
    ]

    print("Reading pipeline shapefile...")

    pipes = gpd.read_file(
        PIPELINE_FILE,
        engine="pyogrio",
        columns=columns,
    )

    print(f"Raw segments: {len(pipes):,}")
    print(f"Raw CRS: {pipes.crs}")

    pipes = pipes.to_crs("EPSG:4326")

    operating_gas = pipes.loc[
        (pipes["SEG_STATUS"] == "Operating")
        & pipes["SUBSTANCE1"].isin(
            ["Natural Gas", "Sour Natural Gas"]
        )
    ].copy()

    operating_gas["OUT_DIAMET"] = pd.to_numeric(
        operating_gas["OUT_DIAMET"],
        errors="coerce",
    )

    operating_gas["SEG_LENGTH"] = pd.to_numeric(
        operating_gas["SEG_LENGTH"],
        errors="coerce",
    )

    ngtl = operating_gas.loc[
        operating_gas["COMP_NAME"]
        == "NOVA Gas Transmission Ltd."
    ].copy()

    major_gas = operating_gas.loc[
        operating_gas["OUT_DIAMET"].ge(200)
    ].copy()

    print(f"Operating gas segments: {len(operating_gas):,}")
    print(f"NGTL operating gas segments: {len(ngtl):,}")
    print(
        "Major operating gas segments >=200 mm: "
        f"{len(major_gas):,}"
    )

    ngtl_output = OUTPUT_DIR / "ngtl_operating_pipelines.geojson"
    major_output = OUTPUT_DIR / "major_operating_gas_pipelines.geojson"
    summary_output = OUTPUT_DIR / "pipeline_company_summary.csv"

    ngtl.to_file(
        ngtl_output,
        driver="GeoJSON",
        engine="pyogrio",
    )

    major_gas.to_file(
        major_output,
        driver="GeoJSON",
        engine="pyogrio",
    )

    company_summary = (
        operating_gas.groupby("COMP_NAME", dropna=False)
        .agg(
            SegmentCount=("PLLICSEGID", "count"),
            TotalLengthKm=("SEG_LENGTH", "sum"),
            AverageDiameterMm=("OUT_DIAMET", "mean"),
        )
        .sort_values("TotalLengthKm", ascending=False)
        .reset_index()
    )

    company_summary.to_csv(
        summary_output,
        index=False,
    )

    print("\nCreated:")
    print(ngtl_output)
    print(major_output)
    print(summary_output)


if __name__ == "__main__":
    main()
