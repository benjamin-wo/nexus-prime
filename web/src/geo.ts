/** Straight-line distances, worked out in the browser from places Google gave us. Google's
 * coordinates are never stored, so nothing here is saved. The same formula as
 * ``metres_between`` on the server (domain/places.py). */

export type Point = { lat: number; lng: number };

const EARTH_METRES = 6_371_000;

/** The great-circle distance between two points, in metres. */
export function metresBetween(a: Point, b: Point): number {
  const rad = (deg: number) => (deg * Math.PI) / 180;
  const la1 = rad(a.lat);
  const la2 = rad(b.lat);
  const dla = la2 - la1;
  const dln = rad(b.lng - a.lng);
  const h = Math.sin(dla / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dln / 2) ** 2;
  return 2 * EARTH_METRES * Math.asin(Math.sqrt(Math.min(1, h)));
}

/** "340 m" under a kilometre, else "1.2 km". */
export function distance(metres: number): string {
  return metres < 1000 ? `${Math.round(metres / 10) * 10} m` : `${(metres / 1000).toFixed(1)} km`;
}
