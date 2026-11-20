// Render args the Python wrappers (app/*_component.py) send to more than one
// map component. Each component's own args extend these.
// A change to one of these args in Python changes it here too.

/** Where pmtiles_server.py is: its own port, or a path on the page's host. */
export interface TileSidecarArgs {
  pmtiles_port: number;
  pmtiles_path_prefix: string;
}

/** Where derivate_bbox_server.py is (raster_bbox_map only). */
export interface DerivateSidecarArgs {
  derivate_bbox_server_port: number;
  derivate_bbox_path_prefix: string;
}

/** Version of a coverage served at /coverage.geojson?v= (see coverage_store.py). */
export interface CoverageArgs {
  coverage_version: string | null;
}

/** WGS84 [[lat_min, lon_min], [lat_max, lon_max]], the order folium used. */
export type LatLonBounds = [[number, number], [number, number]];

export interface MapView {
  lat: number;
  lon: number;
  zoom: number;
}

/** The value the overview and IFK send to Python when the user clicks "Anriss öffnen". */
export interface OpenAnrissValue {
  id_anriss: number;
  /** Tells a fresh click apart from Streamlit repeating the last value on a rerun. */
  nonce: number;
  /** The map's view at the click, so "Zurück" can restore it. */
  view: MapView;
  /** The ticked area classes, restored after "Anriss abwählen". */
  active_areas: number[];
}

/** An LV95 point [E, N]. */
export type Lv95Point = [number, number];

/** A drawn or uploaded area: a closed LV95 ring, last point = first. */
export interface Selection {
  type: "bbox" | "polygon";
  ring: Lv95Point[];
}

/** The value sent to Python after a drawn selection or "Löschen". */
export interface SelectionValue {
  selection: Selection | null;
  /** Tells a fresh action apart from Streamlit repeating the last value on a rerun. */
  nonce: number;
}

declare global {
  interface Window {
    /** The component's map, set right after it is created: for DevTools and tests/components. */
    debugMap?: import("maplibre-gl").Map;
  }
}
