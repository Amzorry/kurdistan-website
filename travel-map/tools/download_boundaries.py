#!/usr/bin/env python3
"""Download and validate geoBoundaries inputs, then build local region GeoJSON.

Run from any working directory:
    python3 travel-map/tools/download_boundaries.py

Only Python's standard library is required. Existing output files are replaced only
once every source file has downloaded, parsed, validated, and all selections match.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
API = "https://www.geoboundaries.org/api/current/gbOpen/{iso}/{level}/"
USER_AGENT = "KurdistanTravelMapBoundaryBuilder/1.0 (local open-data build)"
TIMEOUT = 30

# Editable, explicitly selected administrative areas. These are broad proxies,
# not asserted cultural/legal borders. Names are matched after accent/punctuation
# normalization against the upstream ADM1 feature's shapeName/name properties.
REGIONS = {
    "north": {
        "label": "Northern Kurdistan",
        "iso": "TUR",
        "areaAliases": [[name] for name in [
            "Agri", "Batman", "Bingol", "Bitlis", "Diyarbakir", "Elazig",
            "Hakkari", "Igdir", "Kars", "Malatya", "Mardin", "Mus",
            "Siirt", "Sirnak", "Tunceli", "Van",
        ]],
    },
    "south": {
        "label": "Southern Kurdistan",
        "iso": "IRQ",
        "areaAliases": [
            ["Dahuk", "Duhok", "Dohuk"], ["Erbil", "Arbil"], ["Kirkuk"],
            ["Nineveh", "Ninawa"], ["Salah ad Din", "Saladin", "Salah al-Din"],
            ["Sulaymaniyah", "As Sulaymaniyah", "Al-Sulaimaniyah"], ["Diyala"],
        ],
        "unavailableAreas": [{
            "name": "Halabja",
            "reason": "No Halabja feature is present in the downloaded Iraq ADM1 source; it is excluded rather than assigned another governorate's geometry.",
        }],
    },
    "east": {
        "label": "Eastern Kurdistan",
        "iso": "IRN",
        "areaAliases": [["Azerbaijan Gharbi", "West Azerbaijan"], ["Kermanshah"], ["Kordestan", "Kurdistan"], ["Ilam"]],
    },
    "west": {
        "label": "Western Kurdistan",
        "iso": "SYR",
        "areaAliases": [["Al Hasakah", "Al-Hasakah", "Hasaka"], ["Aleppo", "Halab"], ["Ar Raqqah", "Raqqa"]],
    },
}
COUNTRIES = ("TUR", "IRQ", "IRN", "SYR")


def norm(value: object) -> str:
    import unicodedata
    # Turkish dotless i does not decompose under NFKD. Transliterate it before
    # removing combining marks so Ağrı/Agri, Iğdır/Igdir, etc. compare equally.
    text = str(value or "").translate(str.maketrans({"ı": "i", "İ": "I"}))
    decomposed = unicodedata.normalize("NFKD", text).casefold()
    asciiish = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", asciiish).strip()


def normalized_alias_groups(definition: dict, region_key: str) -> list[set[str]]:
    groups = [{norm(alias) for alias in aliases} for aliases in definition["areaAliases"]]
    owners: dict[str, int] = {}
    for index, group in enumerate(groups):
        for alias in group:
            if not alias:
                raise RuntimeError(f"{region_key}: an administrative-area alias normalizes to an empty name")
            previous = owners.setdefault(alias, index)
            if previous != index:
                first = definition["areaAliases"][previous]
                second = definition["areaAliases"][index]
                raise RuntimeError(f"{region_key}: ambiguous alias {alias!r} is shared by {first} and {second}")
    return groups


def request_json(url: str) -> tuple[object, dict[str, str], int]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            body = response.read()
            content_type = response.headers.get("Content-Type", "")
            status = response.status
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Request failed for {url}: {exc}") from exc
    try:
        data = json.loads(body)
    except Exception as exc:
        raise RuntimeError(f"Not valid JSON from {url} (HTTP {status}, {content_type}, {len(body)} bytes): {exc}") from exc
    return data, {"content_type": content_type, "bytes": str(len(body))}, status


def fetch_metadata(iso: str, level: str) -> dict:
    url = API.format(iso=iso, level=level)
    data, info, status = request_json(url)
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError(f"Invalid metadata response from {url}: HTTP {status}")
    if not data.get("simplifiedGeometryGeoJSON") and not data.get("gjDownloadURL"):
        raise RuntimeError(f"Metadata has no GeoJSON URLs: {url}")
    print(f"metadata {iso} {level}: HTTP {status}; {info['content_type']}; {info['bytes']} bytes")
    return data


def coord_count_and_validate(value: object) -> int:
    count = 0
    def visit(node: object) -> None:
        nonlocal count
        if not isinstance(node, list):
            return
        if len(node) >= 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
            lon, lat = float(node[0]), float(node[1])
            if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180) or not (-90 <= lat <= 90):
                raise ValueError(f"Coordinate outside WGS84 longitude/latitude range: {node[:2]}")
            count += 1
            return
        for child in node:
            visit(child)
    visit(value)
    return count


def validate_geojson(data: object, source_url: str) -> dict:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise RuntimeError(f"Expected a GeoJSON FeatureCollection at {source_url}")
    if not data["features"]:
        raise RuntimeError(f"GeoJSON has no features at {source_url}")
    for index, feature in enumerate(data["features"]):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise RuntimeError(f"Feature {index} is invalid in {source_url}")
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise RuntimeError(f"Feature {index} is not Polygon/MultiPolygon in {source_url}")
        coordinates = geometry.get("coordinates")
        if coord_count_and_validate(coordinates) < 4:
            raise RuntimeError(f"Feature {index} has too few coordinates in {source_url}")
        polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
        if not isinstance(polygons, list) or not polygons:
            raise RuntimeError(f"Feature {index} has no polygon rings in {source_url}")
        for polygon in polygons:
            if not isinstance(polygon, list) or not polygon:
                raise RuntimeError(f"Feature {index} has an empty polygon in {source_url}")
            for ring in polygon:
                if not isinstance(ring, list) or len(ring) < 4:
                    raise RuntimeError(f"Feature {index} has a ring with fewer than four positions in {source_url}")
                if ring[0][:2] != ring[-1][:2]:
                    raise RuntimeError(f"Feature {index} has an unclosed polygon ring in {source_url}")
    return data


def fetch_geometry(meta: dict, label: str) -> tuple[dict, str, dict]:
    candidates = []
    for key in ("simplifiedGeometryGeoJSON", "gjDownloadURL"):
        url = meta.get(key)
        if url and url not in candidates:
            candidates.append(url)
    errors = []
    for url in candidates:
        try:
            raw, info, status = request_json(url)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")
            geojson = validate_geojson(raw, url)
            count = len(geojson["features"])
            coords = sum(coord_count_and_validate(f["geometry"]["coordinates"]) for f in geojson["features"])
            print(f"geometry {label}: HTTP {status}; {info['content_type']}; {info['bytes']} bytes; {count} features; {coords} positions; {url}")
            return geojson, url, info
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
            errors.append(f"{url}: {exc}")
            print(f"geometry attempt failed: {url}: {exc}", file=sys.stderr)
    raise RuntimeError("All GeoJSON download URLs failed for " + label + "\n  " + "\n  ".join(errors))


def feature_name(feature: dict) -> str:
    props = feature.get("properties") or {}
    return str(props.get("shapeName") or props.get("shapeName_en") or props.get("name_en") or props.get("name") or props.get("NAME_1") or "")


def feature_collection(features: list[dict], name: str) -> dict:
    return {"type": "FeatureCollection", "name": name, "features": features}


def load_local_json(path: Path) -> object:
    try:
        return json.loads(path.read_bytes())
    except Exception as exc:
        raise RuntimeError(f"Could not read valid JSON from local source file {path}: {exc}") from exc


def fetch_local_metadata(input_dir: Path, iso: str, level: str) -> dict:
    path = input_dir / f"{iso}-{level}.metadata.json"
    data = load_local_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected a metadata object in {path}")
    if not data.get("simplifiedGeometryGeoJSON") and not data.get("gjDownloadURL"):
        raise RuntimeError(f"Metadata has no GeoJSON URLs: {path}")
    print(f"metadata {iso} {level}: loaded from {path}")
    return data


def fetch_local_geometry(input_dir: Path, meta: dict, iso: str, level: str) -> tuple[dict, str, dict]:
    # The manual browser workflow stores the simplified file first and the full
    # geometry as a fallback. We still validate both the metadata URL and data.
    candidates = (
        (input_dir / f"{iso}-{level}.simplified.geojson", "simplifiedGeometryGeoJSON"),
        (input_dir / f"{iso}-{level}.full.geojson", "gjDownloadURL"),
    )
    errors = []
    for path, metadata_key in candidates:
        url = meta.get(metadata_key)
        if not url or not path.is_file():
            continue
        try:
            raw = load_local_json(path)
            geojson = validate_geojson(raw, url)
            size = path.stat().st_size
            coords = sum(coord_count_and_validate(f["geometry"]["coordinates"]) for f in geojson["features"])
            info = {"content_type": "application/geo+json (local file)", "bytes": str(size)}
            print(f"geometry {iso} {level}: local file {path}; {size} bytes; {len(geojson['features'])} features; {coords} positions; source {url}")
            return geojson, url, info
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
            print(f"local geometry attempt failed: {path}: {exc}", file=sys.stderr)
    details = "\n  ".join(errors) if errors else "no matching local geometry files were found"
    raise RuntimeError(f"No valid local geometry for {iso} {level} in {input_dir}:\n  {details}")


def download_all(input_dir: Path | None = None) -> dict[str, bytes]:
    sources: dict[tuple[str, str], tuple[dict, dict, str]] = {}
    for iso in COUNTRIES:
        for level in ("ADM0", "ADM1"):
            if input_dir is None:
                meta = fetch_metadata(iso, level)
                geo, url, info = fetch_geometry(meta, f"{iso} {level}")
            else:
                meta = fetch_local_metadata(input_dir, iso, level)
                geo, url, info = fetch_local_geometry(input_dir, meta, iso, level)
            sources[(iso, level)] = (geo, meta, url)

    outputs: dict[str, bytes] = {}
    manifest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "geoBoundaries gbOpen current API; each source's boundaryLicense is retained below",
        "coordinateReferenceSystem": "WGS84 longitude, latitude (GeoJSON / EPSG:4326)",
        "interpretation": "Administrative-area coverage proxies selected explicitly in tools/download_boundaries.py; not universally agreed Kurdistan boundaries.",
        "regions": {}, "sources": {},
    }

    for iso, level in sources:
        geo, meta, url = sources[(iso, level)]
        manifest["sources"][f"{iso}-{level}"] = {
            "boundaryID": meta.get("boundaryID"), "boundaryName": meta.get("boundaryName"),
            "boundaryYearRepresented": meta.get("boundaryYearRepresented"),
            "boundarySource": meta.get("boundarySource"), "boundaryLicense": meta.get("boundaryLicense"),
            "licenseSource": meta.get("licenseSource"), "sourceDataUpdateDate": meta.get("sourceDataUpdateDate"),
            "downloadedFrom": url,
        }

    for key, definition in REGIONS.items():
        geo, meta, url = sources[(definition["iso"], "ADM1")]
        alias_groups = normalized_alias_groups(definition, key)
        matched_groups: set[int] = set()
        feature_by_group: dict[int, str] = {}
        selected = []
        for feature in geo["features"]:
            name = feature_name(feature)
            normalized = norm(name)
            matching_groups = [i for i, group in enumerate(alias_groups) if normalized in group]
            if len(matching_groups) > 1:
                raise RuntimeError(f"{key}: source feature name {name!r} ambiguously matches multiple selected areas")
            if matching_groups:
                group_index = matching_groups[0]
                if group_index in feature_by_group:
                    raise RuntimeError(f"{key}: aliases for {definition['areaAliases'][group_index]} match multiple source features: {feature_by_group[group_index]!r} and {name!r}")
                feature_by_group[group_index] = name
                props = dict(feature.get("properties") or {})
                props.update({
                    "_region": key,
                    "_regionLabel": definition["label"],
                    "_coverageUnitName": name,
                    "_sourceBoundaryID": meta.get("boundaryID"),
                    "_sourceYear": meta.get("boundaryYearRepresented"),
                    "_sourceLicense": meta.get("boundaryLicense"),
                    "_sourceURL": url,
                })
                selected.append({**feature, "properties": props})
                matched_groups.add(group_index)
        missing = [definition["areaAliases"][i] for i in range(len(alias_groups)) if i not in matched_groups]
        if missing:
            available = ", ".join(feature_name(f) for f in geo["features"])
            raise RuntimeError(f"{key}: source features did not match selected name groups {missing}. Available source names: {available}")
        out = feature_collection(selected, definition["label"])
        for f in out["features"]:
            validate_geojson(feature_collection([f], definition["label"]), f"selected {key} feature")
        outputs[f"regions/{key}.geojson"] = (json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        manifest["regions"][key] = {
            "label": definition["label"], "countryISO": definition["iso"],
            "selection": definition["areaAliases"], "matchedFeatures": [feature_name(f) for f in selected],
            "featureCount": len(selected), "sourceBoundaryID": meta.get("boundaryID"),
            "sourceYear": meta.get("boundaryYearRepresented"), "sourceLicense": meta.get("boundaryLicense"),
            "unavailableAreas": [
                {**area, "sourceBoundaryID": meta.get("boundaryID"),
                 "sourceYear": meta.get("boundaryYearRepresented")}
                for area in definition.get("unavailableAreas", [])
            ],
        }

    country_features = []
    for iso in COUNTRIES:
        geo, meta, url = sources[(iso, "ADM0")]
        for feature in geo["features"]:
            props = dict(feature.get("properties") or {})
            props.update({"_countryCode": iso, "_sourceBoundaryID": meta.get("boundaryID"),
                          "_sourceYear": meta.get("boundaryYearRepresented"),
                          "_sourceLicense": meta.get("boundaryLicense"), "_sourceURL": url})
            country_features.append({**feature, "properties": props})
    countries = feature_collection(country_features, "National outlines; distinct from illustrative regional coverage")
    outputs["countries.geojson"] = (json.dumps(countries, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    outputs["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return outputs


def atomic_write(outputs: dict[str, bytes]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    temp_paths: list[tuple[Path, Path]] = []
    try:
        for relative, content in outputs.items():
            target = DATA / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
            temp = Path(temp_name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
            temp_paths.append((temp, target))
        for temp, target in temp_paths:
            temp.replace(target)
    finally:
        for temp, _ in temp_paths:
            if temp.exists():
                temp.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download or locally assemble validated geoBoundaries regional files.")
    parser.add_argument("--input-dir", type=Path, help="Use saved metadata/GeoJSON inputs instead of network requests")
    args = parser.parse_args(argv)
    try:
        outputs = download_all(args.input_dir.resolve() if args.input_dir else None)
        manifest = json.loads(outputs["manifest.json"])
        atomic_write(outputs)
    except Exception as exc:
        print(f"Boundary build failed; existing files were not replaced.\n{exc}", file=sys.stderr)
        return 1
    print("Selected source areas:")
    for key, region in manifest["regions"].items():
        print(f"  {key}: matched {', '.join(region['matchedFeatures'])}")
        for area in region.get("unavailableAreas", []):
            print(f"  {key}: unavailable {area['name']} — {area['reason']}")
    print("Validated local boundary files written:")
    for relative, content in outputs.items():
        print(f"  {DATA / relative} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
