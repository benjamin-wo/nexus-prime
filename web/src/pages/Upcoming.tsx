import type { DepartmentView } from "../departments";

/** A department that isn't built yet: what it will do, instead of empty pages. */
export function Upcoming({ department }: { department: DepartmentView }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>
            <span aria-hidden="true">{department.icon}</span> {department.label}
          </h1>
          <p className="muted">{department.blurb}</p>
        </div>
      </div>
      <section className="card" aria-label={`About ${department.label}`}>
        <p>{department.upcoming}</p>
        <p className="caption">Coming next. Nothing to set up yet.</p>
      </section>
    </>
  );
}
