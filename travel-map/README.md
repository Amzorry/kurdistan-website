# Standalone Kurdistan travel map

This page uses Leaflet 1.9.4 with the standard OpenStreetMap raster tile URL: `https://tile.openstreetmap.org/{z}/{x}/{y}.png`. The map starts at a wide view over southeastern Turkey, northern Iraq, western Iran, and northeastern Syria. The four region controls move to approximate viewports; they do not draw or claim precise regional boundaries.

The initial basemap does not depend on the geoBoundaries downloader or any regional GeoJSON. Road networks, settlements, rivers, and other mapped features are rendered from the visible OpenStreetMap tiles. Four local city records and two local town guide points are separately selectable and searchable; their GeoNames IDs and source links are stored in `data/places.geojson` and `data/guide-points.geojson`.

## Run locally

From the project root:

```sh
python3 -m http.server 8000
```

Open `http://localhost:8000/travel-map/`. The page also uses relative local data URLs, so it can be served from a GitHub Pages project path.

Do not open `index.html` directly with a `file://` URL. OpenStreetMap's public tile service expects web-page requests to include a valid HTTP `Referer`; a local-file page has no normal HTTP page origin to send. The page sets `strict-origin-when-cross-origin`, which lets browsers send the site origin on cross-origin tile requests without spoofing request headers.

## Tile service terms and attribution

No API key is required. The standard `tile.openstreetmap.org` service is community-funded, best-effort, and has no SLA or numeric free request quota. Requests are limited to visible Leaflet map tiles; this page has no tile prefetch or offline download. Browser caching is left at its default. Keep the visible Leaflet attribution and page Referer intact. If the site grows beyond modest interactive use, use a hosted tile provider with published capacity/terms or self-host tiles. Read the current [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

The app uses the exact OSM tile endpoint and a standard browser User-Agent/Referer. Tile failures show the failed tile URL and a retry action without hiding the map controls or local place data.

## Places, search, location, and routing

- Local points: GeoNames, CC BY 4.0; source IDs and record URLs are included in the GeoJSON. The additional guide towns Akre and Rawanduz have GeoNames records at [Akre](https://www.geonames.org/445694/-akra.html) and [Rawanduz](https://www.geonames.org/92002/ruwandiz.html).
- Search checks local points first. Broader visitor-submitted queries use OpenStreetMap Nominatim at most once per second and are cached locally. See the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/). If it is unavailable, local search and the tile map remain usable.
- Geolocation is only requested after the visitor taps the location button and grants browser permission. The page shows actual coordinates and does not classify them against unverified regional boundaries.
- Optional driving directions use FOSSGIS OSRM only after the visitor requests a route. This is a best-effort public service with no production availability promise; see [service information](https://routing.openstreetmap.de/about.html).

The old geoBoundaries downloader and source files are retained for future use but are not a prerequisite for rendering this page.
