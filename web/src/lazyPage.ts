import { type ComponentType, lazy } from "react";

const RELOADED = "nexus-chunk-reloaded";

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** A page's code is fetched when its route is first opened. If that fetch fails (usually a deploy
 * replaced the file the open page still points at), reload once to pick up the new build, then
 * give up and let the error boundary speak, so a real outage can't loop. */
export function lazyPage<T extends ComponentType<any>>(load: () => Promise<{ default: T }>) {
  return lazy(async () => {
    const store = storage();
    try {
      const page = await load();
      try {
        store?.removeItem(RELOADED);
      } catch {
        // Not being able to clear the guard only costs a second recovery later.
      }
      return page;
    } catch (e) {
      let reload = false;
      try {
        if (store && store.getItem(RELOADED) !== "1") {
          store.setItem(RELOADED, "1");
          reload = true;
        }
      } catch {
        reload = false;
      }
      if (!reload) throw e;
      window.location.reload();
      // Keep the loading line up until the reload lands.
      return new Promise<never>(() => undefined);
    }
  });
}

/** `lazyPage` for a module that exports its page by name. */
export function lazyNamed<M extends Record<string, unknown>, K extends keyof M & string>(
  load: () => Promise<M>,
  name: K,
) {
  return lazyPage(async () => ({ default: (await load())[name] as Extract<M[K], ComponentType<any>> }));
}
