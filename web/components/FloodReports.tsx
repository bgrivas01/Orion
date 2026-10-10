import type { FloodReport } from "@orion/shared";

interface Props {
  reports: FloodReport[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

export default function FloodReports({ reports, loading, error, onRefresh }: Props) {
  return (
    <section className="mx-4 mb-6 rounded-lg p-3" aria-labelledby="reports-heading"
      style={{ background: "var(--surface)", border: "1px solid var(--border)" }}>
      <div className="flex items-center justify-between gap-2">
        <h2 id="reports-heading" className="text-sm font-semibold">Flood reports</h2>
        <button type="button" onClick={onRefresh} disabled={loading}
          className="rounded px-2 py-1 text-xs disabled:opacity-40"
          style={{ border: "1px solid var(--border)" }}>
          {loading ? "Loading…" : "Refresh"}
        </button>
      </div>
      <p className="mt-1 text-[11px]" style={{ color: "var(--text-secondary)" }}>
        Observations shown as squares on the map. Check report times; water levels may
        have changed. Reports do not affect route scores yet.
      </p>
      {error && <p role="status" className="mt-2 text-xs">{error}</p>}
      {!loading && !error && reports.length === 0 &&
        <p className="mt-2 text-xs">No flood reports available.</p>}
      <ul className="mt-2 space-y-2">
        {reports.map((report) => (
          <li key={report.id} className="rounded p-2 text-xs"
            style={{ border: "1px solid var(--border)" }}>
            <p className="font-medium">{report.location_name || "Unnamed location"}</p>
            <p className="mt-1">
              {report.severity || "Severity unknown"} · {report.water_depth_inches == null
                ? "Depth unknown" : `${report.water_depth_inches} inches of water`}
            </p>
            {report.description && <p className="mt-1">{report.description}</p>}
            <p className="mt-1" style={{ color: "var(--text-secondary)" }}>
              {report.reported_at
                ? <time dateTime={report.reported_at}>{new Date(report.reported_at).toLocaleString()}</time>
                : "Report time unknown"}
              {(report.latitude == null || report.longitude == null) && " · Location not mapped"}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
