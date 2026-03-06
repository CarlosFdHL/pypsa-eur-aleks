# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT
"""
Build regionalised geological sequestration potential for carbon dioxide using
data from `CO2Stop <https://setis.ec.europa.eu/european-co2-storage-
database_en>`_.
"""

from typing import Any, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely.geometry as sg
from shapely.ops import unary_union

# --- CARLOS CHANGE: import missing libraries ---
import subprocess
import tempfile
from pathlib import Path
# --- END OF CARLOS CHANGE ---------------------------------------------------------------------

CRS = "EPSG:4326"

def convert_to_2d(
    geom: Union[sg.base.BaseGeometry, Any],
) -> Union[sg.base.BaseGeometry, Any]:
    """
    Remove the third dimension (z-coordinate) from a shapely geometry object.

    Parameters
    ----------
    geom : shapely.geometry
        A shapely geometry object which may contain 3D coordinates

    Returns
    -------
    shapely.geometry
        The same type of geometry with only 2D coordinates (x,y)

    Raises
    ------
    RuntimeError
        If the geometry type is not supported
    """
    if geom is None or geom.is_empty:
        return geom

    # Handle coordinates directly for simple geometries
    if isinstance(geom, (sg.Point, sg.LineString, sg.LinearRing)):
        return type(geom)([xy[0:2] for xy in list(geom.coords)])

    # Handle Polygon
    elif isinstance(geom, sg.Polygon):
        new_exterior = convert_to_2d(geom.exterior)
        new_interiors = [convert_to_2d(interior) for interior in geom.interiors]
        return sg.Polygon(new_exterior, new_interiors)

    # Handle collections of geometries
    elif isinstance(
        geom,
        (sg.MultiPoint, sg.MultiLineString, sg.MultiPolygon, sg.GeometryCollection),
    ):
        return type(geom)([convert_to_2d(part) for part in geom.geoms])

    else:
        raise RuntimeError(f"Geometry type {type(geom)} is not supported.")


# # CARLOS CHANGE ---------------------------------------------------------------------------
# def create_capacity_map_storage(table_fn: str, map_fn: str) -> gpd.GeoDataFrame:
#     df = pd.read_csv(table_fn)

#     gdf_raw = gpd.read_file(map_fn)

#     # --- CHANGE: normalize an ID column to "ID" (handles KML->GeoJSON variants) ---
#     rename_map = {}
#     if "id" in gdf_raw.columns:
#         rename_map["id"] = "ID"
#     elif "ID" in gdf_raw.columns:
#         pass
#     elif "ID2" in gdf_raw.columns:
#         rename_map["ID2"] = "ID"
#     elif "Name" in gdf_raw.columns:
#         # Last resort: use Name as ID (not ideal, but prevents hard crash)
#         rename_map["Name"] = "ID"
#     else:
#         raise KeyError(
#             f"No ID-like column found in storage map. Columns: {list(gdf_raw.columns)}"
#         )

#     gdf = gdf_raw.rename(columns=rename_map)

#     sel = ["COUNTRYCOD", "ID", "geometry"]
#     missing = [c for c in sel if c not in gdf.columns]
#     if missing:
#         raise KeyError(
#             f"Missing columns {missing} in storage map after renaming. Columns: {list(gdf.columns)}"
#         )

#     gdf = gdf[sel]

#     # --- Build estimates in df FIRST (as in original code) ---
#     df["conservative estimate Mt"] = (
#         df["EST_STORECAP_MIN"]
#         .replace(0, np.nan)
#         .fillna(df["STORE_CAP_MIN"])
#         .add(df.get("STORE_CAP_HCDAUGHTER", 0))
#         .fillna(0)
#     )

#     df["neutral estimate Mt"] = (
#         df["EST_STORECAP_MEAN"]
#         .replace(0, np.nan)
#         .fillna(df["STORE_CAP_MEAN"])
#         .add(df.get("STORE_CAP_HCDAUGHTER", 0))
#         .replace(0, np.nan)
#         .fillna(df["conservative estimate Mt"])
#     )

#     df["optimistic estimate Mt"] = (
#         df["EST_STORECAP_MAX"]
#         .replace(0, np.nan)
#         .fillna(df["STORE_CAP_MAX"])
#         .add(df.get("STORE_CAP_HCDAUGHTER", 0))
#         .replace(0, np.nan)
#         .fillna(df["neutral estimate Mt"])
#     )

#     # --- CHANGE: ensure clustered rule expected columns exist ---
#     df["conservative estimate GAS Mt"] = 0.0
#     df["conservative estimate OIL Mt"] = 0.0
#     df["conservative estimate aquifer Mt"] = 0.0

#     # Keep only what you need for the merge
#     sel_df = [
#         "STORAGE_UNIT_ID",
#         "STORAGE_UNIT_NAME",
#         "ASSESS_UNIT_TYPE",
#         "conservative estimate Mt",
#         "neutral estimate Mt",
#         "optimistic estimate Mt",
#         "conservative estimate GAS Mt",
#         "conservative estimate OIL Mt",
#         "conservative estimate aquifer Mt",
#     ]
#     df = df[sel_df]

#     # Merge capacities into gdf
#     gdf = gdf.merge(df, left_on="ID", right_on="STORAGE_UNIT_ID", how="left").drop(
#         "STORAGE_UNIT_ID", axis=1
#     )

#     # --- CHANGE: enforce required numeric columns (avoid None -> crashes later) ---
#     req = [
#         "conservative estimate Mt",
#         "conservative estimate GAS Mt",
#         "conservative estimate OIL Mt",
#         "conservative estimate aquifer Mt",
#     ]
#     extra = ["neutral estimate Mt", "optimistic estimate Mt"]
#     for c in req + extra:
#         if c not in gdf.columns:
#             gdf[c] = 0.0
#         gdf[c] = pd.to_numeric(gdf[c], errors="coerce").fillna(0.0)

#     original_crs = gdf.crs

#     # --- CHANGE: repair geometries BEFORE dissolve (prevents TopologyException) ---
#     # Prefer shapely.make_valid if available, otherwise fallback to buffer(0)
#     gdf = gdf.set_geometry("geometry")
#     gdf = gdf[~gdf.geometry.isna()]
#     gdf = gdf[~gdf.geometry.is_empty]

#     try:
#         from shapely import make_valid  # shapely >= 2.0
#         gdf["geometry"] = gdf["geometry"].apply(make_valid)
#     except Exception:
#         gdf["geometry"] = gdf["geometry"].buffer(0)

#     invalid = ~gdf.is_valid
#     if invalid.any():
#         # Fix remaining invalid geometries
#         gdf.loc[invalid, "geometry"] = gdf.loc[invalid, "geometry"].buffer(0)

#     # --- CHANGE: safe dissolve (avoid geopandas internal union_all hard-fail) ---
#     from shapely.ops import unary_union
#     from shapely.errors import GEOSException

#     def _safe_union(geoms):
#         geoms = [g for g in geoms if g is not None and (not g.is_empty)]
#         if not geoms:
#             return None
#         try:
#             return unary_union(geoms)
#         except GEOSException:
#             # Try fixing each geom and retry
#             fixed = []
#             for gg in geoms:
#                 try:
#                     from shapely import make_valid  # may exist
#                     fixed.append(make_valid(gg))
#                 except Exception:
#                     fixed.append(gg.buffer(0))
#             fixed = [g for g in fixed if g is not None and (not g.is_empty)]
#             return unary_union(fixed) if fixed else None

#     group_cols = ["COUNTRYCOD", "ID"]

#     # Numeric sums
#     g_num = gdf.groupby(group_cols, as_index=False).agg({c: "sum" for c in req + extra})

#     # Keep first strings (optional)
#     if "STORAGE_UNIT_NAME" in gdf.columns:
#         g_name = gdf.groupby(group_cols, as_index=False).agg({"STORAGE_UNIT_NAME": "first"})
#         g_num = g_num.merge(g_name, on=group_cols, how="left")
#     if "ASSESS_UNIT_TYPE" in gdf.columns:
#         g_type = gdf.groupby(group_cols, as_index=False).agg({"ASSESS_UNIT_TYPE": "first"})
#         g_num = g_num.merge(g_type, on=group_cols, how="left")

#     # Geometry union (safe)
#     g_geom = (
#         gdf.groupby(group_cols)["geometry"]
#         .apply(_safe_union)
#         .reset_index(name="geometry")
#     )

#     gdf = g_num.merge(g_geom, on=group_cols, how="left")
#     gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=original_crs)

#     # --- CHANGE: final cleanup for any remaining small issues ---
#     gdf = gdf[~gdf.geometry.isna()]
#     gdf["geometry"] = gdf["geometry"].buffer(0)

#     gdf.set_geometry("geometry", inplace=True)
#     gdf.set_crs(CRS, inplace=True)

#     return gdf
# # END OF CARLOS CHANGE ---------------------------------------------------------------------


def create_capacity_map_storage(table_fn: str, map_fn: str) -> gpd.GeoDataFrame:
    """
    Create a GeoDataFrame of CO2 storage capacities.

    Parameters
    ----------
    table_fn : str
        Path to CSV file containing storage capacity data
    map_fn : str
        Path to geographic file containing storage unit geometries

    Returns
    -------
    gpd.GeoDataFrame    
        GeoDataFrame with storage units and their capacity estimates
    """
    df = pd.read_csv(table_fn)

    sel = ["COUNTRYCOD", "ID", "geometry"]

    # CARLOS CHANGE ---------------------------------------------------------------------------
    # Try with ID, else ID2, else Name (last resort)
    if "id" in gpd.read_file(map_fn).columns:
        id_col = "id"
    elif "ID" in gpd.read_file(map_fn).columns:
        id_col = "ID"
    elif "ID2" in gpd.read_file(map_fn).columns:
        id_col = "ID2"
    elif "Name" in gpd.read_file(map_fn).columns:
        id_col = "Name"
    else:
        raise KeyError(f"No ID-like column found in storage map. Columns: {gpd.read_file(map_fn).columns}")
    
    gdf = gpd.read_file(map_fn).rename(columns={id_col: "ID"})[sel]
    # gdf = gpd.read_file(map_fn).rename(columns={"id": "ID"})[sel]

    # -----------------------------------------------------------------------------------------
    gdf.geometry = gdf.geometry.buffer(0)

    # Combine shapes with the same id into one multi-polygon
    gdf = gdf.groupby(["COUNTRYCOD", "ID"]).agg(unary_union).reset_index()
    gdf.set_geometry("geometry", inplace=True)
    gdf.set_crs(CRS, inplace=True)

    # conservative estimate: use MIN
    df["conservative estimate Mt"] = (
        df["EST_STORECAP_MIN"]
        .replace(0, np.nan)
        .fillna(df["STORE_CAP_MIN"])
        .add(df["STORE_CAP_HCDAUGHTER"])
        .fillna(0)
    )

    # neutral estimate: use MEAN
    df["neutral estimate Mt"] = (
        df["EST_STORECAP_MEAN"]
        .replace(0, np.nan)
        .fillna(df["STORE_CAP_MEAN"])
        .add(df["STORE_CAP_HCDAUGHTER"])
        .replace(0, np.nan)
        .fillna(df["conservative estimate Mt"])
    )

    # optimistic estimate: use MAX
    df["optimistic estimate Mt"] = (
        df["EST_STORECAP_MAX"]
        .replace(0, np.nan)
        .fillna(df["STORE_CAP_MAX"])
        .add(df["STORE_CAP_HCDAUGHTER"])
        .replace(0, np.nan)
        .fillna(df["neutral estimate Mt"])
    )

    sel = [
        "STORAGE_UNIT_ID",
        "STORAGE_UNIT_NAME",
        "ASSESS_UNIT_TYPE",
        "conservative estimate Mt",
        "neutral estimate Mt",
        "optimistic estimate Mt",
    ]
    df = df[sel]

    gdf = gdf.merge(df, left_on="ID", right_on="STORAGE_UNIT_ID", how="left").drop(
        "STORAGE_UNIT_ID", axis=1
    )
    return gdf



def create_capacity_map_traps(table_fn: list[str], map_fn: str) -> gpd.GeoDataFrame:
    """
    Create a GeoDataFrame of CO2 trap capacities.

    Parameters
    ----------
    table_fn : list[str]
        List of paths to CSV files containing trap capacity data
    map_fn : str
        Path to geographic file containing trap geometries

    Returns
    -------
    gpd.GeoDataFrame
        GeoDataFrame with traps and their capacity estimates for different
        types (aquifer, oil, gas) and scenarios (conservative, neutral, optimistic)
    """
    df = pd.concat([pd.read_csv(path) for path in table_fn], ignore_index=True)

    sel = ["COUNTRYCOD", "ID", "geometry"]

    # CARLOS CHANGE ---------------------------------------------------------------------------
    # Try with ID, else ID2, else Name (last resort)
    if "id" in gpd.read_file(map_fn).columns:
        id_col = "id"
    elif "ID" in gpd.read_file(map_fn).columns:
        id_col = "ID"
    elif "ID2" in gpd.read_file(map_fn).columns:
        id_col = "ID2"
    elif "Name" in gpd.read_file(map_fn).columns:
        id_col = "Name"
    else:
        raise KeyError(f"No ID-like column found in storage map. Columns: {gpd.read_file(map_fn).columns}")
    
    gdf = gpd.read_file(map_fn).rename(columns={id_col: "ID"})[sel]
    # gdf = gpd.read_file(map_fn).rename(columns={"id": "ID"})[sel]

    # -----------------------------------------------------------------------------------------
    # Combine shapes with the same id into one multi-polygon
    gdf = gdf.groupby(["COUNTRYCOD", "ID"]).agg(unary_union).reset_index()
    gdf.set_geometry("geometry", inplace=True)
    gdf.set_crs(CRS, inplace=True)

    # conservative estimate: use MIN
    df["conservative estimate aquifer Mt"] = (
        df["EST_STORECAP_MIN"].replace(0, np.nan).fillna(df["STORE_CAP_MIN"])
    )
    df["conservative estimate OIL Mt"] = (
        df["MIN_EST_STORE_CAP_OIL"]
        .replace(0, np.nan)
        .fillna(df["MIN_CALC_STORE_CAP_OIL"])
    )
    df["conservative estimate GAS Mt"] = (
        df["MIN_EST_STORE_CAP_GAS"]
        .replace(0, np.nan)
        .fillna(df["MIN_CALC_STORE_CAP_GAS"])
    )

    sel = [
        "conservative estimate aquifer Mt",
        "conservative estimate OIL Mt",
        "conservative estimate GAS Mt",
    ]
    df["conservative estimate Mt"] = df[sel].sum(axis=1).fillna(0)

    # neutral estimate: use MEAN
    df["neutral estimate aquifer Mt"] = (
        df["EST_STORECAP_MEAN"].replace(0, np.nan).fillna(df["STORE_CAP_MEAN"])
    )
    df["neutral estimate OIL Mt"] = (
        df["MEAN_EST_STORE_CAP_OIL"]
        .replace(0, np.nan)
        .fillna(df["MEAN_CALC_STORE_CAP_OIL"])
    )
    df["neutral estimate GAS Mt"] = (
        df["MEAN_EST_STORE_CAP_GAS"]
        .replace(0, np.nan)
        .fillna(df["MEAN_CALC_STORE_CAP_GAS"])
    )

    sel = [
        "neutral estimate aquifer Mt",
        "neutral estimate OIL Mt",
        "neutral estimate GAS Mt",
    ]
    df["neutral estimate Mt"] = (
        df[sel].sum(axis=1).replace(0, np.nan).fillna(df["conservative estimate Mt"])
    )

    # optimistic estimate: use MAX
    df["optimistic estimate aquifer Mt"] = (
        df["EST_STORECAP_MAX"].replace(0, np.nan).fillna(df["STORE_CAP_MAX"])
    )
    df["optimistic estimate OIL Mt"] = (
        df["MAX_EST_STORE_CAP_OIL"]
        .replace(0, np.nan)
        .fillna(df["MAX_CALC_STORE_CAP_OIL"])
    )
    df["optimistic estimate GAS Mt"] = (
        df["MAX_EST_STORE_CAP_GAS"]
        .replace(0, np.nan)
        .fillna(df["MAX_CALC_STORE_CAP_GAS"])
    )

    sel = [
        "optimistic estimate aquifer Mt",
        "optimistic estimate OIL Mt",
        "optimistic estimate GAS Mt",
    ]
    df["optimistic estimate Mt"] = (
        df[sel].sum(axis=1).replace(0, np.nan).fillna(df["neutral estimate Mt"])
    )

    sel = [
        "TRAP_ID",
        "TRAP_NAME",
        "ASSESS_UNIT_TYPE",
        "optimistic estimate Mt",
        "neutral estimate Mt",
        "conservative estimate Mt",
        "optimistic estimate aquifer Mt",
        "optimistic estimate OIL Mt",
        "optimistic estimate GAS Mt",
        "neutral estimate aquifer Mt",
        "neutral estimate OIL Mt",
        "neutral estimate GAS Mt",
        "conservative estimate aquifer Mt",
        "conservative estimate OIL Mt",
        "conservative estimate GAS Mt",
    ]
    df = df[sel]

    gdf = gdf.merge(df, left_on="ID", right_on="TRAP_ID", how="left").drop(
        "TRAP_ID", axis=1
    )

    return gdf


def merge_maps(
    traps_map: gpd.GeoDataFrame, storage_map: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    """
    Merge trap and storage map GeoDataFrames into a single map.

    Parameters
    ----------
    traps_map : gpd.GeoDataFrame
        GeoDataFrame containing trap geometries and capacity data
    storage_map : gpd.GeoDataFrame
        GeoDataFrame containing storage unit geometries and capacity data

    Returns
    -------
    gpd.GeoDataFrame
        Combined GeoDataFrame with all geometries and capacity data
    """
    # Ensure both DataFrames have the same columns
    missing_in_traps = set(storage_map.columns) - set(traps_map.columns)
    missing_in_storage = set(traps_map.columns) - set(storage_map.columns)
    for col in missing_in_traps:
        traps_map[col] = 0
    for col in missing_in_storage:
        storage_map[col] = 0

    storage_map["geometry"] = storage_map["geometry"].apply(convert_to_2d)
    traps_map["geometry"] = traps_map["geometry"].apply(convert_to_2d)

    gdf = gpd.GeoDataFrame(pd.concat([storage_map, traps_map]), crs=CRS)

    gdf.drop_duplicates(inplace=True)

    return gdf


# if __name__ == "__main__":
    # if "snakemake" not in globals():
    #     from scripts._helpers import mock_snakemake

    #     snakemake = mock_snakemake("build_co2_storage")

    # table_fn = snakemake.input.storage_table
    # map_fn = snakemake.input.storage_map
    # storage_map = create_capacity_map_storage(table_fn, map_fn)

    # table_fn = [
    #     snakemake.input.traps_table1,
    #     snakemake.input.traps_table2,
    #     snakemake.input.traps_table3,
    # ]
    # map_fn = snakemake.input.traps_map
    # traps_map = create_capacity_map_traps(table_fn, map_fn)

    # gdf = merge_maps(traps_map, storage_map)

    # gdf.to_file(snakemake.output[0])

# CARLOS CHANGE: moved the main block to the top to include the KML->GeoJSON workaround. 
if __name__ == "__main__":
    if "snakemake" not in globals():
        from scripts._helpers import mock_snakemake

        snakemake = mock_snakemake("build_co2_storage")

    # --- KML -> GeoJSON workaround (Fiona has no KML driver in this env) ---
    base_tmp = Path(getattr(snakemake.resources, "tmpdir", "/tmp"))
    tmpdir = Path(tempfile.mkdtemp(prefix="co2stop_kml_", dir=str(base_tmp)))


    storageunits_kml = snakemake.input.storage_map
    daughterunits_kml = snakemake.input.traps_map

    su_geojson = tmpdir / "StorageUnits_March13.geojson"
    du_geojson = tmpdir / "DaughterUnits_March13.geojson"

    subprocess.run(["ogr2ogr", "-f", "GeoJSON", str(su_geojson), storageunits_kml], check=True)
    subprocess.run(["ogr2ogr", "-f", "GeoJSON", str(du_geojson), daughterunits_kml], check=True)

    # --- now run the usual pipeline but with GeoJSON paths ---
    table_fn = snakemake.input.storage_table
    storage_map = create_capacity_map_storage(table_fn, str(su_geojson))

    table_fn = [
        snakemake.input.traps_table1,
        snakemake.input.traps_table2,
        snakemake.input.traps_table3,
    ]
    traps_map = create_capacity_map_traps(table_fn, str(du_geojson))

    gdf = merge_maps(traps_map, storage_map)
    gdf.to_file(snakemake.output[0])