# Third-party licenses

PGR-Atlas uses the open source software listed here. The lists were generated
on 2026-11-18 from the lockfiles. Each license is given as an
[SPDX identifier](https://spdx.org/licenses/) and links to its license text.

To update them after a dependency change, read the license and homepage from
the installed packages again: the Python ones from their metadata
(`importlib.metadata`), for the packages `uv export --no-dev` lists, and the
JavaScript ones from the `package.json` of each package that
`npm ls --omit=dev --all` lists in `frontend/`. A package that declares an SPDX
expression (`License-Expression`, or `license` in `package.json`) keeps it. For
one that declares only a name such as "BSD License", read its `LICENSE` file
and write the matching identifier. The link goes to the license's page on
spdx.org, or to the package's own license file where its text differs from the
SPDX one (matplotlib).

## Python packages in the image

Everything `uv.lock` installs into the image: the app's dependencies in
`pyproject.toml` and what they depend on. Development tools (pytest, ruff,
Playwright) are not in the image and not listed.

| Package | Version | License | Homepage |
|---|---|---|---|
| affine | 3.0.1 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/rasterio/affine |
| altair | 6.3.0 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/vega/altair |
| anyio | 4.15.1 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/agronholm/anyio |
| attrs | 26.1.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://www.attrs.org/ |
| boto3 | 1.44.0 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/boto/boto3 |
| botocore | 1.44.5 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/boto/botocore |
| certifi | 2026.10.19 | [MPL-2.0](https://spdx.org/licenses/MPL-2.0.html) | https://github.com/certifi/python-certifi |
| charset-normalizer | 3.5.1 | [MIT](https://spdx.org/licenses/MIT.html) | https://charset-normalizer.readthedocs.io/ |
| click | 8.5.0 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/pallets/click/ |
| click-plugins | 1.1.1.2 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/click-contrib/click-plugins |
| cligj | 0.7.2 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/mapbox/cligj |
| contourpy | 1.3.3 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/contourpy/contourpy |
| cycler | 0.12.1 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://matplotlib.org/cycler/ |
| duckdb | 2.0.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/duckdb/duckdb-python |
| fonttools | 4.66.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/fonttools/fonttools |
| geopandas | 1.1.4 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://geopandas.org |
| h11 | 0.16.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/python-hyper/h11 |
| idna | 3.20 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/kjd/idna |
| itsdangerous | 2.2.0 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/pallets/itsdangerous/ |
| Jinja2 | 3.1.6 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/pallets/jinja/ |
| jmespath | 1.1.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/jmespath/jmespath.py |
| jsonschema | 4.26.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/python-jsonschema/jsonschema |
| jsonschema-specifications | 2025.9.1 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/python-jsonschema/jsonschema-specifications |
| kiwisolver | 1.5.1 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/nucleic/kiwi |
| MarkupSafe | 3.0.3 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/pallets/markupsafe/ |
| matplotlib | 3.11.2 | [PSF-2.0](https://github.com/matplotlib/matplotlib/tree/v3.11.2/LICENSE) | https://matplotlib.org |
| narwhals | 2.26.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/narwhals-dev/narwhals |
| numpy | 2.4.6 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) AND [0BSD](https://spdx.org/licenses/0BSD.html) AND [MIT](https://spdx.org/licenses/MIT.html) AND [Zlib](https://spdx.org/licenses/Zlib.html) AND [CC0-1.0](https://spdx.org/licenses/CC0-1.0.html) | https://numpy.org |
| packaging | 26.3 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) OR [BSD-2-Clause](https://spdx.org/licenses/BSD-2-Clause.html) | https://github.com/pypa/packaging |
| pandas | 2.3.3 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://pandas.pydata.org |
| pillow | 13.0.0 | [MIT-CMU](https://spdx.org/licenses/MIT-CMU.html) | https://python-pillow.org |
| protobuf | 7.36.2 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://developers.google.com/protocol-buffers/ |
| psutil | 7.2.2 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/giampaolo/psutil |
| pyarrow | 26.0.1 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://arrow.apache.org/ |
| pydeck | 0.9.3 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/visgl/deck.gl/tree/master/bindings/pydeck |
| pyogrio | 0.12.1 | [MIT](https://spdx.org/licenses/MIT.html) | https://pyogrio.readthedocs.io/ |
| pyparsing | 3.3.3 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/pyparsing/pyparsing/ |
| pyproj | 3.7.2 | [MIT](https://spdx.org/licenses/MIT.html) | https://pyproj4.github.io/pyproj/ |
| python-dateutil | 2.9.0.post0 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) OR [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/dateutil/dateutil |
| python-dotenv | 1.2.4 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/theskumar/python-dotenv |
| python-multipart | 0.0.32 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/Kludex/python-multipart |
| pytz | 2026.4 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/stub42/pytz |
| rasterio | 1.4.4 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/rasterio/rasterio |
| referencing | 0.37.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/python-jsonschema/referencing |
| requests | 2.34.2 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/psf/requests |
| rpds-py | 2026.6.3 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/crate-py/rpds |
| s3transfer | 0.19.2 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/boto/s3transfer |
| shapely | 2.1.2 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/shapely/shapely |
| six | 1.17.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/benjaminp/six |
| starlette | 1.7.0 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/Kludex/starlette |
| streamlit | 1.67.0 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://streamlit.io |
| tornado | 6.6.1 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/tornadoweb/tornado |
| typing_extensions | 4.16.0 | [PSF-2.0](https://spdx.org/licenses/PSF-2.0.html) | https://github.com/python/typing_extensions |
| tzdata | 2026.4 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/python/tzdata |
| urllib3 | 2.8.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://urllib3.readthedocs.io |
| uvicorn | 0.54.0 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://uvicorn.dev/ |
| vl-convert-python | 1.9.0.post1 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/jonmmease/vl-convert |
| watchdog | 6.0.0 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/gorakhargosh/watchdog/ |
| websockets | 16.1.1 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/python-websockets/websockets |

## JavaScript packages in the map components

The libraries that `frontend/` bundles into `app/<component>/dist/`
(`maplibre-gl`, `@mapbox/mapbox-gl-draw`, `pmtiles`, `proj4`) and their
dependencies, from `frontend/package-lock.json`. Build tools (Vite, TypeScript,
ESLint, Prettier, Vitest) are not shipped and not listed.

| Package | Version | License | Homepage |
|---|---|---|---|
| @mapbox/geojson-area | 0.2.2 | [BSD-2-Clause](https://spdx.org/licenses/BSD-2-Clause.html) | https://github.com/mapbox/geojson-area |
| @mapbox/geojson-normalize | 0.0.1 | [ISC](https://spdx.org/licenses/ISC.html) | https://github.com/mapbox/geojson-normalize |
| @mapbox/jsonlint-lines-primitives | 2.0.3 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/mapbox/jsonlint |
| @mapbox/mapbox-gl-draw | 1.5.2 | [ISC](https://spdx.org/licenses/ISC.html) | https://github.com/mapbox/mapbox-gl-draw |
| @mapbox/point-geometry | 1.1.0 | [ISC](https://spdx.org/licenses/ISC.html) | https://github.com/mapbox/point-geometry |
| @mapbox/tiny-sdf | 2.3.0 | [BSD-2-Clause](https://spdx.org/licenses/BSD-2-Clause.html) | https://github.com/mapbox/tiny-sdf#readme |
| @mapbox/unitbezier | 1.0.0 | [BSD-2-Clause](https://spdx.org/licenses/BSD-2-Clause.html) | https://github.com/mapbox/unitbezier |
| @mapbox/vector-tile | 3.0.0 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/mapbox/vector-tile-js |
| @maplibre/geojson-vt | 6.3.0 | [ISC](https://spdx.org/licenses/ISC.html) | https://github.com/maplibre/geojson-vt |
| @maplibre/maplibre-gl-style-spec | 26.6.0 | [ISC](https://spdx.org/licenses/ISC.html) | https://maplibre.org/maplibre-style-spec/ |
| @maplibre/mlt | 1.3.0 | [MIT](https://spdx.org/licenses/MIT.html) OR [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html) | https://github.com/maplibre/maplibre-tile-spec/#readme |
| @maplibre/vt-pbf | 4.3.3 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/maplibre/vt-pbf |
| @turf/clone | 7.4.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/Turfjs/turf |
| @turf/helpers | 7.4.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/Turfjs/turf |
| @turf/meta | 7.4.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/Turfjs/turf |
| @turf/projection | 7.4.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/Turfjs/turf |
| @types/geojson | 7946.0.16 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/DefinitelyTyped/DefinitelyTyped/tree/master/types/geojson |
| bidi-js | 1.1.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/lojjic/bidi-js |
| earcut | 3.2.4 | [ISC](https://spdx.org/licenses/ISC.html) | https://github.com/mapbox/earcut |
| fast-deep-equal | 3.1.3 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/epoberezkin/fast-deep-equal#readme |
| fflate | 0.8.3 | [MIT](https://spdx.org/licenses/MIT.html) | https://101arrowz.github.io/fflate |
| gl-matrix | 3.4.4 | [MIT](https://spdx.org/licenses/MIT.html) | http://glmatrix.net |
| json-stringify-pretty-compact | 4.0.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/lydell/json-stringify-pretty-compact |
| kdbush | 4.1.0 | [ISC](https://spdx.org/licenses/ISC.html) | https://github.com/mourner/kdbush |
| maplibre-gl | 6.17.0 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://maplibre.org/ |
| mgrs | 1.0.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/proj4js/mgrs |
| minimist | 1.2.8 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/minimistjs/minimist |
| murmurhash-js | 1.0.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/mikolalysenko/murmurhash-js |
| nanoid | 6.0.1 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/ai/nanoid |
| pbf | 5.1.2 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/mapbox/pbf |
| pmtiles | 4.5.0 | [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) | https://github.com/protomaps/pmtiles |
| potpack | 2.1.0 | [ISC](https://spdx.org/licenses/ISC.html) | https://mapbox.github.io/potpack/ |
| proj4 | 2.22.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://proj4js.github.io/proj4js/ |
| protocol-buffers-schema | 3.6.1 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/mafintosh/protocol-buffers-schema |
| quickselect | 3.0.0 | [ISC](https://spdx.org/licenses/ISC.html) | https://github.com/mourner/quickselect |
| require-from-string | 2.0.2 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/floatdrop/require-from-string |
| resolve-protobuf-schema | 2.1.0 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/mafintosh/resolve-protobuf-schema |
| tinyqueue | 3.0.0 | [ISC](https://spdx.org/licenses/ISC.html) | https://github.com/mourner/tinyqueue |
| tslib | 2.8.1 | [0BSD](https://spdx.org/licenses/0BSD.html) | https://www.typescriptlang.org/ |
| wgs84 | 0.0.0 | [BSD-2-Clause](https://spdx.org/licenses/BSD-2-Clause.html) | https://github.com/mapbox/wgs84 |
| wkt-parser | 1.5.6 | [MIT](https://spdx.org/licenses/MIT.html) | https://github.com/proj4js/wkt-parser#readme |

## Also shipped

| What | License | Source |
|---|---|---|
| Roboto 2.137, weights 300, 400, 500 and 700 (`app/static/fonts/`, bundled into the map components) | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html); the text is in `LICENSE.txt` next to the files | https://github.com/googlefonts/roboto, as published in the Kanton Bern web style guide (https://kantonbern.snowflake.ch/styleguides/1/Kanton-Bern/) |
| Roboto Regular, glyph range 0-255, for the map labels (`frontend/public/glyphs/roboto-regular/`), generated from `roboto-400.woff` with fontnik 0.7.7 | [Apache-2.0](https://spdx.org/licenses/Apache-2.0.html); the text is in `LICENSE.txt` next to the file | https://github.com/googlefonts/roboto, as above |
| Python 3.12 and the Debian packages of the base image `python:3.12-slim-trixie` | [PSF-2.0](https://spdx.org/licenses/PSF-2.0.html) for Python; the Debian packages carry their own licenses under `/usr/share/doc/*/copyright` in the image | https://hub.docker.com/_/python |
| Native libraries inside the Python wheels (the `*.libs/` folders next to the packages): GDAL, PROJ, libcurl, libtiff and others; GEOS in shapely and rasterio; libgfortran and libquadmath in numpy | Each its own; mostly permissive. GEOS is [LGPL-2.1-only](https://spdx.org/licenses/LGPL-2.1-only.html), libquadmath [LGPL-2.1-or-later](https://spdx.org/licenses/LGPL-2.1-or-later.html), libgfortran [GPL-3.0-or-later WITH GCC-exception-3.1](https://spdx.org/licenses/GCC-exception-3.1.html). All are linked dynamically and ship unchanged; the license texts are in each wheel's `*.dist-info/` | The package homepages above |
| The Kanton Bern logo (`app/static/logo-be.svg`), in the sidebar | Not covered by this repo's BSD 3-Clause License: a mark of Kanton Bern, all rights reserved. Don't reuse it in a derived work | Kanton Bern |
| The Škerlak Data + Analytics logo (`app/static/logo_2026_wide.svg`, in the sidebar) and its small square version (`app/static/logo_2026_small.svg`, the favicon) | Not covered by this repo's BSD 3-Clause License: marks of Škerlak Data + Analytics, all rights reserved. Don't reuse them in a derived work | Škerlak Data + Analytics |
| DuckDB extensions `httpfs` and `spatial`, installed into the image at build time | see the projects; `spatial` bundles GDAL, GEOS and PROJ | https://github.com/duckdb/duckdb-httpfs, https://github.com/duckdb/duckdb-spatial |

## Not shipped, used at runtime

The basemap tiles come from swisstopo (`wmts.geo.admin.ch`) and, if the user
picks it, from OpenStreetMap (`tile.openstreetmap.org`). Their terms of use
apply to the map data, and the maps show the attribution.
