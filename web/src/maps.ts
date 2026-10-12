/** Google's Maps JavaScript API, loaded once when a trip page first shows a map.
 *
 * The key is the browser key from the trip (limited in Google Cloud to this site and
 * the Maps JavaScript API), never the server's. Only the few parts the trip map uses
 * are typed here. A key Google refuses calls `gm_authFailure`, which turns into the
 * map's "couldn't load" message. */

export type LatLng = { lat: number; lng: number };

export interface GMap {
  fitBounds(bounds: GBounds, padding?: number): void;
  setCenter(at: LatLng): void;
  setZoom(zoom: number): void;
  panTo(at: LatLng): void;
}
export interface GOverlay {
  setMap(map: GMap | null): void;
}
export interface GMarker extends GOverlay {
  addListener(event: "click", handler: () => void): unknown;
}
export interface GBounds {
  extend(at: LatLng): void;
}

export interface MapsApi {
  Map: new (element: HTMLElement, options: Record<string, unknown>) => GMap;
  Marker: new (options: Record<string, unknown>) => GMarker;
  Polyline: new (options: Record<string, unknown>) => GOverlay;
  LatLngBounds: new () => GBounds;
  /** google.maps.SymbolPath.CIRCLE, for round pins. */
  circle: unknown;
}

type Library = Record<string, unknown>;
type GoogleMaps = { importLibrary(name: string): Promise<Library> };

const READY = "__nexusMapsReady";
let pending: Promise<MapsApi> | null = null;
const failures = new Set<() => void>();

/** Calls ``handler`` if Google refuses the key (even after the map has loaded). */
export function onMapsAuthFailure(handler: () => void): () => void {
  failures.add(handler);
  return () => failures.delete(handler);
}

export function loadMaps(key: string): Promise<MapsApi> {
  if (pending) return pending;
  pending = new Promise<MapsApi>((resolve, reject) => {
    const w = window as unknown as Record<string, unknown>;
    w.gm_authFailure = () => failures.forEach((f) => f());
    w[READY] = () => {
      const maps = (w.google as { maps?: GoogleMaps } | undefined)?.maps;
      if (!maps) return reject(new Error("The map couldn't load"));
      Promise.all([maps.importLibrary("maps"), maps.importLibrary("marker"), maps.importLibrary("core")])
        .then(([m, marker, core]) =>
          resolve({
            Map: m.Map as MapsApi["Map"],
            Polyline: m.Polyline as MapsApi["Polyline"],
            Marker: marker.Marker as MapsApi["Marker"],
            LatLngBounds: core.LatLngBounds as MapsApi["LatLngBounds"],
            circle: (core.SymbolPath as { CIRCLE: unknown } | undefined)?.CIRCLE ?? 0,
          }),
        )
        .catch(reject);
    };
    const script = document.createElement("script");
    const params = new URLSearchParams({ key, v: "weekly", loading: "async", callback: READY });
    script.src = `https://maps.googleapis.com/maps/api/js?${params}`;
    script.async = true;
    // Google checks the key against this site: send our origin, never a path.
    script.referrerPolicy = "origin";
    script.onerror = () => {
      pending = null;
      reject(new Error("The map couldn't load"));
    };
    document.head.append(script);
  });
  return pending;
}
