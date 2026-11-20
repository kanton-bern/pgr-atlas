// derivate_bbox_server.py's /bbox.png answers with the crop's pixel-snapped
// corners in an X-Corners header, which place the image on the map.

type LonLat = [number, number];
/** Top left, top right, bottom right, bottom left. */
export type Corners = [LonLat, LonLat, LonLat, LonLat];

/** The crop's 4 [lon, lat] corners from X-Corners; null if missing or malformed. */
export function parseCorners(header: string | null): Corners | null {
  let corners: unknown;
  try {
    corners = JSON.parse(header ?? "");
  } catch {
    return null;
  }
  const isPoint = (c: unknown) =>
    Array.isArray(c) &&
    c.length === 2 &&
    c.every((v) => typeof v === "number" && Number.isFinite(v));
  return Array.isArray(corners) && corners.length === 4 && corners.every(isPoint)
    ? (corners as Corners)
    : null;
}
