import { useState } from "react";

import { Button, ButtonLink, Chip, ChipGroup, Figure, Row, RowList, Section, Tabs } from "../components/ui";
import { BodyMap } from "../health/body/BodyMap";

/**
 * Every building block in components/ui, in each of its states, with made-up figures: a page to review the look
 * in light and dark, on a phone and a wide screen. Dev only: App.tsx registers /dev/blocks behind
 * import.meta.env.DEV, so this never ships.
 */
export function BlocksGallery() {
  const [filter, setFilter] = useState("All");
  const [saved, setSaved] = useState(false);
  const [pressed, setPressed] = useState(0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Building blocks gallery</h1>
          <p className="caption">Every block in components/ui, with made-up figures. Dev builds only.</p>
        </div>
      </div>

      <Section id="g-buttons" title="Buttons">
        <div className="stack" style={{ paddingBlock: "var(--space-3)" }}>
          <div className="quick">
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button>Plain (cancel, back)</Button>
            <Button variant="text">Text</Button>
            <Button variant="danger">Delete</Button>
          </div>
          <div className="quick">
            <Button variant="primary" size="sm">
              Small primary
            </Button>
            <Button variant="secondary" size="sm">
              Small secondary
            </Button>
            <Button variant="text" size="sm">
              Small text
            </Button>
            <Button variant="primary" disabled>
              Disabled
            </Button>
            <Button disabled>Disabled plain</Button>
          </div>
          <div className="quick">
            <ButtonLink variant="secondary" to="/accounting/budgets">
              ButtonLink (route)
            </ButtonLink>
            <ButtonLink variant="text" href="https://example.com" target="_blank" rel="noopener noreferrer">
              ButtonLink (href)
            </ButtonLink>
          </div>
          <Button variant="primary" full>
            Full width
          </Button>
        </div>
      </Section>

      <Section id="g-chips" title="Chips">
        <div className="stack" style={{ paddingBlock: "var(--space-3)" }}>
          <ChipGroup aria-label="Show">
            {["All", "Spent", "Received", "Pending"].map((f) => (
              <Chip key={f} pressed={filter === f} onClick={() => setFilter(f)}>
                {f}
              </Chip>
            ))}
          </ChipGroup>
          <ChipGroup aria-label="Chip states">
            <Chip pressed={false}>Off</Chip>
            <Chip pressed>On</Chip>
            <Chip>Acts only</Chip>
            <Chip disabled>Disabled</Chip>
            <Chip to="/travel">A link chip</Chip>
            <Chip to="/accounting" pressed>
              A current link chip
            </Chip>
          </ChipGroup>
        </div>
      </Section>

      <Section id="g-tabs" title="Sub-tabs">
        <div style={{ paddingBlock: "var(--space-2)" }}>
          <Tabs
            label="Gallery pages"
            items={[
              { to: "/dev/blocks", label: "Blocks", end: true },
              { to: "/accounting", label: "Overview", end: true },
              { to: "/accounting/ledger", label: "Ledger" },
              { to: "/accounting/budgets", label: "Budgets" },
            ]}
          />
        </div>
      </Section>

      <Section
        id="g-rows"
        title="Rows in a section"
        action={
          <Button variant="text" size="sm">
            See all 8
          </Button>
        }
      >
        <RowList aria-label="Example rows">
          <Row title="Just a title" />
          <Row title="Corner bakery" sub="Food · Thursday" trailing="12.40" />
          <Row title="Check in at Hotel Example" sub="Sampleton, from 3 pm" trailing="Today" />
          <Row title="Weekly groceries" sub="A route link: the whole row opens it" trailing="86.15" to="/accounting/ledger" />
          <Row
            title="Pressed this row"
            sub={`A button row, pressed ${pressed} time${pressed === 1 ? "" : "s"}`}
            trailing="Look"
            onClick={() => setPressed((n) => n + 1)}
          />
          <Row
            title="Dinner with friends"
            sub="Split three ways"
            trailing="54.00"
            actions={
              <>
                <Button variant="text" size="sm" onClick={() => setSaved(!saved)}>
                  {saved ? "Settled" : "Settle"}
                </Button>
                <Button variant="danger" size="sm">
                  Remove
                </Button>
              </>
            }
          />
          <Row
            title="A very long title that has to wrap onto a second line on a narrow phone screen"
            sub="And a sub-line that is also fairly long, so it wraps too"
            trailing="1,234,567.89"
          />
        </RowList>
      </Section>

      <Section id="g-empty" title="An empty section">
        <p className="state">Nothing here yet.</p>
      </Section>

      <Section id="g-figures" title="Figures">
        <div className="stack" style={{ paddingBlock: "var(--space-3)" }}>
          <div className="tiles">
            <Figure label="Spent this month" value="SGD 1,357.40" extra="42% of the budget" />
            <Figure label="Left to spend" value="SGD 1,842.60" />
            <Figure label="Loading" value="…" />
          </div>
          <div className="mini-tiles">
            <Figure size="sm" label="Budget left" value="1,842.60" extra="58% left" />
            <Figure size="sm" label="A usual month" value="2,140.00" extra="Last six months" />
            <Figure size="sm" label="Saved" value="19%" />
          </div>
        </div>
      </Section>

      <Section id="g-bodymap" title="Body map">
        <div className="stack" style={{ paddingBlock: "var(--space-3)" }}>
          <p className="caption">Primary is the accent, secondary the same accent lighter. Health, Gym.</p>
          <BodyMap view="both" size={300} primary={["chest", "quadriceps"]} secondary={["triceps", "shoulders", "glutes", "lats"]} />
          <BodyMap view="front" size={200} primary={["abdominals"]} secondary={["adductors"]} />
        </div>
      </Section>
    </>
  );
}
