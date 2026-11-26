import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api, type ScreenshotRead, type TripDetail } from "../api";
import { Icon } from "../components/Icon";
import { base64 } from "../files";
import { type AddPreset, AddSheet } from "./TripAdd";
import { PhotoCredit, coverStyle, day, isMember, sharedBy, todayIso, tripWhen, useHome } from "./TripBits";
import { type Fix, type Go, type Stage, stageOf } from "./TripStage";
import { ArrangeProvider } from "./TripArrange";
import { TripMap } from "./TripMap";
import { TripPlacesProvider } from "./TripPlaces";
import { IdeasTab, listOf } from "./TripIdeas";
import { MoneyTab } from "./TripMoney";
import { ActivityLine } from "./TripActivity";
import { PrepTab } from "./TripPrep";
import { TripFaces, hasMembers, useMembers } from "./TripPeople";
import { ShareSheet } from "./TripShare";
import { Button, ButtonLink } from "../components/ui";

import "./travel.css";
import { Itinerary, DAY_MS, tripDays } from "./TripItinerary";
import { NextUpStrip, TripActions, useCoverGone } from "./TripHeader";
import { TripForm } from "./TripsPage";

export { tripWhen };
export { TripsPage } from "./TripsPage";

const TABS = [
  ["plan", "Plan"],
  ["ideas", "Ideas"],
  ["money", "Money"],
  ["prep", "Prep"],
] as const;
type Tab = (typeof TABS)[number][0];
const isTab = (value: string | null): value is Tab => TABS.some(([tab]) => tab === value);

/** The trip's idea lists so far: where a new idea can be filed. */
function ideaLists(detail: TripDetail): string[] {
  const lists = detail.bookings.filter((b) => b.kind === "activity" && !b.scheduled).map((b) => listOf(b)?.trim() ?? "");
  return [...new Set(lists.filter(Boolean))];
}

/** One trip, on one page that follows it: Plan, Ideas, Money and Prep as tabs, and under
 * the header the one thing to do next. It opens on Plan, or on Money once it's over. */
export function TripPage({ onAsk }: { onAsk?: (text: string) => void } = {}) {
  const { id = "" } = useParams();
  const client = useQueryClient();
  const navigate = useNavigate();
  const home = useHome();
  const [params, setParams] = useSearchParams();
  const detail = useQuery({
    queryKey: ["trip", id],
    queryFn: () => api<TripDetail>(`/travel/trips/${id}`),
    // Someone else's change turns up when the window comes back; a 404 (removed, or left) is an answer, not a blip to retry.
    refetchOnWindowFocus: true,
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 3,
  });
  // Taken off the trip (or it's gone): the server tells a person with no part in a trip there is no such trip.
  const gone = detail.error instanceof ApiError && detail.error.status === 404;
  const [editing, setEditing] = useState(false);
  const [sheet, setSheet] = useState<{ preset: AddPreset | null } | null>(null);
  const [sharing, setSharing] = useState(false);
  const [reading, setReading] = useState(false);
  const [imported, setImported] = useState<string | null>(null);
  const [shotError, setShotError] = useState<string | null>(null);
  // The + on Money and Prep: the tab opens its own form.
  const [addingCost, setAddingCost] = useState(false);
  const [addingPacking, setAddingPacking] = useState(false);
  // The map shows every day, not just the one open.
  const [mapAll, setMapAll] = useState(false);
  const data = gone ? undefined : detail.data;
  const member = data ? isMember(data.trip) : false;
  const members = useMembers(id, Boolean(data));
  const stage: Stage = data ? stageOf(data) : "planning";
  const refresh = () =>
    Promise.all([
      client.invalidateQueries({ queryKey: ["trip", id] }),
      client.invalidateQueries({ queryKey: ["trips"] }),
      client.invalidateQueries({ queryKey: ["trip-places", id] }),
      // A change to the day can change who goes where, and so the travel times.
      client.invalidateQueries({ queryKey: ["trip-hops", id] }),
    ]);

  // The open tab lives in the address, so Back goes to the one before.
  // A member has no Money tab: money is the owner's, so its address opens Plan.
  const asked = params.get("tab");
  const tab: Tab = isTab(asked) && !(member && asked === "money") ? asked : stage === "after" && !member ? "money" : "plan";
  useEffect(() => {
    if (member && asked === "money") {
      setParams(
        (was) => {
          const query = new URLSearchParams(was);
          query.set("tab", "plan");
          return query;
        },
        { replace: true },
      );
    }
  }, [member, asked, setParams]);
  // A trip that's gone from the list too, so it isn't offered again.
  useEffect(() => {
    if (gone) void client.invalidateQueries({ queryKey: ["trips"] });
  }, [gone, client]);
  // A + pressed on one tab doesn't wait for the next visit to it.
  useEffect(() => {
    setAddingCost(false);
    setAddingPacking(false);
  }, [tab]);
  // The day open on Plan, shared with the map and the Ideas tab: today while the trip
  // is on, else its first day, until one is picked.
  const days = useMemo(() => (data ? tripDays(data) : []), [data]);
  const today = todayIso();
  const startDay = data && data.trip.status === "ongoing" && days.includes(today) ? today : data && days.includes(data.trip.start) ? data.trip.start : (days[0] ?? "");
  const picked = params.get("day");
  const selectedDay = picked && days.includes(picked) ? picked : startDay;

  function open(next: Tab, onDay?: string) {
    setParams((was) => {
      const query = new URLSearchParams(was);
      query.set("tab", next);
      if (onDay) query.set("day", onDay);
      return query;
    });
    if (onDay) setMapAll(false);
  }

  function pickDay(iso: string) {
    setMapAll(false);
    setParams(
      (was) => {
        const query = new URLSearchParams(was);
        query.set("day", iso);
        return query;
      },
      { replace: true },
    );
  }

  function fix(f: Fix) {
    if (f === "budget") {
      // The budget is the owner's.
      if (!member) setEditing(true);
    } else setSheet({ preset: f });
  }

  function go(to: Go) {
    if ("fix" in to) fix(to.fix);
    else if (to.tab === "plan" || (to.tab === "ideas" && to.day)) open(to.tab, to.day);
    else open(to.tab);
  }

  async function screenshot(file: File) {
    setShotError(null);
    setImported(null);
    setReading(true);
    try {
      const read = await api<ScreenshotRead>(`/travel/trips/${id}/screenshot`, {
        method: "POST",
        body: { image: await base64(file), mime_type: file.type || "image/png" },
      });
      setImported(read.message);
      refresh();
    } catch (e) {
      setShotError(e instanceof Error ? e.message : "Couldn't read that screenshot");
    } finally {
      setReading(false);
    }
  }

  async function remove() {
    if (!data) return;
    await api(`/travel/trips/${id}`, { method: "DELETE" });
    void client.invalidateQueries({ queryKey: ["trips"] });
    navigate("/travel");
  }

  // The one + on each tab: what it's called, and what it does.
  const dayNo = data ? Math.round((Date.parse(selectedDay) - Date.parse(data.trip.start)) / DAY_MS) + 1 : 0;
  const adds: Record<Tab, { label: string; run: () => void }> = {
    plan: { label: data && dayNo >= 1 && dayNo <= data.trip.days ? `Add to Day ${dayNo}` : "Add to this day", run: () => setSheet({ preset: null }) },
    ideas: { label: "Add an idea", run: () => setSheet({ preset: { kind: "place" } }) },
    money: { label: "Add a planned cost", run: () => setAddingCost(true) },
    prep: { label: "Add to prep", run: () => setAddingPacking(true) },
  };
  const add = adds[tab];
  const canAdd = stage !== "after";

  // The big cover is Plan's; on the other tabs, or once the photo has scrolled away, a slim sticky bar stands in.
  const cover = tab === "plan";
  const photo = useRef<HTMLDivElement>(null);
  const coverGone = useCoverGone(photo, cover);
  const away = cover && coverGone;
  const slim = !cover || away;
  const actions = data ? (
    <TripActions
      trip={data.trip}
      member={member}
      editing={editing}
      add={canAdd ? add : null}
      onShare={() => setSharing(true)}
      onEdit={() => setEditing(true)}
      onDelete={remove}
      onChange={refresh}
    />
  ) : null;
  const dates = data ? `${day(data.trip.start)} – ${day(data.trip.end)}` : "";
  const SlimName = cover ? "p" : "h1";

  return (
    <div className="trip-page trip-v2" data-tab={tab} data-cover={cover && !away ? "in" : "out"}>
      {slim && (
        <div className="trip-slim" data-over={cover || undefined}>
          <Link className="trip-icon-button" to="/travel" aria-label="Back to trips">
            <Icon name="chevron" size={20} className="icon-back" />
          </Link>
          <span className="trip-slim-thumb" style={data ? coverStyle(data.trip) : undefined} aria-hidden="true" />
          <div className="trip-slim-title">
            <SlimName className="trip-slim-name">{data?.trip.destination ?? "Trip"}</SlimName>
            {data && <span className="trip-slim-dates">{dates}</span>}
          </div>
          {actions}
        </div>
      )}
      {cover && (
        <header className="trip-hero">
          <div ref={photo} className={`trip-hero-photo${data?.trip.photo ? "" : " no-photo"}`} style={data ? coverStyle(data.trip) : undefined}>
            <div className="trip-hero-bar" aria-hidden={away || undefined} inert={away}>
              <ButtonLink className="trip-bar-button" to="/travel" aria-label="Back to trips">
                <Icon name="chevron" size={16} className="icon-back" />
                Trips
              </ButtonLink>
              {actions}
            </div>
            {data?.trip.photo && (
              <div className="trip-hero-credit" aria-hidden={away || undefined} inert={away}>
                <PhotoCredit photo={data.trip.photo} />
              </div>
            )}
          </div>
          <div className="trip-hero-body">
            <h1 className="trip-hero-title">{data?.trip.destination ?? "Trip"}</h1>
            {data && (
              <p className="trip-hero-meta">
                <span>
                  {dates} · {data.trip.days} {data.trip.days === 1 ? "day" : "days"}
                </span>
                <span className="pill">{tripWhen(data.trip)}</span>
                <TripFaces trip={data.trip} members={members.data} />
              </p>
            )}
            {data && member && <p className="trip-hero-shared">{sharedBy(data.trip)}</p>}
            {data && <NextUpStrip detail={data} onGo={go} />}
            {data && <ActivityLine tripId={id} shared={hasMembers(members.data)} />}
          </div>
        </header>
      )}
      {detail.isLoading && <p className="state">Loading…</p>}
      {gone && (
        <section className="card trip-gone" aria-labelledby="trip-gone">
          <h2 id="trip-gone">This trip isn't here any more.</h2>
          <p className="caption">It may have been deleted, or you were taken off it.</p>
          <div className="actions">
            <ButtonLink variant="secondary" to="/travel">
              Go to your trips
            </ButtonLink>
          </div>
        </section>
      )}
      {detail.isError && !gone && (
        <p className="error-text" role="alert">
          {detail.error instanceof Error ? detail.error.message : "Couldn't load that trip."}
        </p>
      )}
      {data && editing && (
        <section className="card" aria-labelledby="edit-trip" data-no-reveal>
          <div className="card-head">
            <h2 id="edit-trip">Change the trip</h2>
          </div>
          <TripForm
            initial={data.trip}
            home={home}
            onDone={(saved) => {
              setEditing(false);
              if (saved) refresh();
            }}
          />
        </section>
      )}
      {data && (
        <TripPlacesProvider tripId={id} destination={data.trip.destination} enabled={data.places} ideas={data.ideas ?? false} detail={data} onChange={refresh}>
          <ArrangeProvider detail={data} days={days} on={stage !== "after"} onChange={refresh}>
          {reading && (
            <p className="state" role="status">
              Reading the screenshot…
            </p>
          )}
          {shotError && (
            <p className="error-text" role="alert">
              {shotError}
            </p>
          )}
          {imported && (
            <section className="card import-banner" role="status" aria-label="Imported from a screenshot">
              <p style={{ whiteSpace: "pre-line", margin: 0 }}>{imported}</p>
              <p className="caption">Does everything look right?</p>
              <span className="quick">
                <Button variant="secondary" size="sm" onClick={() => setImported(null)}>
                  Looks right
                </Button>
                <Button
                  size="sm"
                  onClick={() => {
                    setImported(null);
                    open("plan");
                    window.setTimeout(() => document.getElementById("itinerary")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
                  }}
                >
                  Fix something
                </Button>
              </span>
            </section>
          )}

          <div className="trip-tabbar">
            <nav className="trip-tabs" aria-label="Trip sections">
              {TABS.filter(([name]) => !(member && name === "money")).map(([name, label]) => (
                <button key={name} type="button" className="trip-tab" aria-current={tab === name ? "page" : undefined} onClick={() => open(name)}>
                  {label}
                </button>
              ))}
            </nav>
          </div>

          {tab === "plan" && (
            <>
              <div className="plan-layout">
                <Itinerary detail={data} day={selectedDay} onDay={pickDay} onChange={refresh} onAdd={(preset) => setSheet({ preset })} onIdeas={() => open("ideas")} />
                <TripMap
                  detail={data}
                  day={mapAll ? null : selectedDay}
                  selected={selectedDay}
                  onDay={(iso) => (iso === null ? setMapAll(true) : pickDay(iso))}
                />
              </div>
              {onAsk && stage !== "after" && (
                <Button
                  variant="text" className="trip-ask"
                  onClick={() =>
                    onAsk(
                      // A member's chat sees the plan only: no budget to ask about.
                      member
                        ? `How's the ${data.trip.destination} trip shared with me looking? What's booked and what's missing?`
                        : `How's my ${data.trip.destination} trip looking? What's booked, what's missing and what's left in the budget?`,
                    )
                  }
                >
                  Ask Nexus about this trip
                </Button>
              )}
            </>
          )}
          {tab === "ideas" && <IdeasTab detail={data} onChange={refresh} viewing={selectedDay || null} />}
          {tab === "money" && (
            <div className="trip-narrow trip-money-tab">
              <MoneyTab detail={data} onChange={refresh} adding={addingCost} onAddDone={() => setAddingCost(false)} />
            </div>
          )}
          {tab === "prep" && (
            <div className="trip-narrow trip-prep-tab">
              <PrepTab detail={data} onChange={refresh} onFix={fix} adding={addingPacking} onAddDone={() => setAddingPacking(false)} />
            </div>
          )}

          {stage !== "after" && (
            <button type="button" className="fab trip-fab-button" aria-label={add.label} onClick={add.run}>
              <Icon name="plus" size={20} />
              Add
            </button>
          )}
          {sheet && (
            <AddSheet
              trip={data.trip}
              preset={sheet.preset}
              places={data.places || (data.ideas ?? false)}
              lists={ideaLists(data)}
              viewing={selectedDay || null}
              onScreenshot={(file) => void screenshot(file)}
              onChanged={refresh}
              onClose={() => setSheet(null)}
            />
          )}
          {sharing && <ShareSheet trip={data.trip} onClose={() => setSharing(false)} onLeft={() => navigate("/travel")} />}
          </ArrangeProvider>
        </TripPlacesProvider>
      )}
    </div>
  );
}
