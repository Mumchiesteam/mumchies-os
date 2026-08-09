import { useEffect, useState } from "react";
import { formatMoney } from "../services/orders";
import {
  getDashboard,
  type DashboardData,
  type DashboardPreset,
} from "../services/dashboard";
import { PeriodSelector } from "./PeriodSelector";
import { attentionClass, attentionTone } from "../utils/semanticFormatting";

const attention: [keyof DashboardData["needs_attention"], string][] = [
  ["fresh", "Fresh Orders"],
  ["follow_up", "Follow-up"],
  ["on_hold", "On Hold"],
  ["ready_booking", "Ready / Pending Booking"],
  ["active_ndr", "Active NDR"],
  ["ndr_over_sla", "NDR Over SLA"],
  ["reconciliation_exceptions", "Reconciliation Exceptions"],
];

export function DashboardPage({
  onNavigate,
}: {
  onNavigate: (target: keyof DashboardData["needs_attention"]) => void;
}) {
  const today = new Date().toISOString().slice(0, 10);
  const [preset, setPreset] = useState<DashboardPreset>("today");
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    let retryTimer: number | undefined;
    void getDashboard(preset, start, end)
      .then((value) => {
        if (!active) return;
        setData(value);
        setError(value.refresh_error || "");
        if (value.refreshing)
          retryTimer = window.setTimeout(
            () => setRetry((value) => value + 1),
            5_000,
          );
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason.message);
        if (String(reason.message).includes("preparing"))
          retryTimer = window.setTimeout(
            () => setRetry((value) => value + 1),
            3_000,
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [preset, start, end, retry]);
  const refreshFor = (change: () => void) => {
    setLoading(true);
    setError("");
    change();
  };
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-[#ff6b35]">Dashboard</p>
          <h2 className="mt-1 text-2xl font-bold tracking-tight">
            Operations overview
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            {data?.period.label || "Current management view"}
            {data?.last_refreshed_at
              ? ` · Last refreshed ${new Date(data.last_refreshed_at).toLocaleString("en-IN")}`
              : ""}
            {data?.refreshing ? " · refreshing…" : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <PeriodSelector
            prefix="Dashboard"
            preset={preset}
            start={start}
            end={end}
            onChange={(next, from, to) =>
              refreshFor(() => {
                setPreset(next);
                setStart(from);
                setEnd(to);
              })
            }
          />
          <button
            onClick={() => {
              setLoading(true);
              setError("");
              void getDashboard(preset, start, end, true)
                .then(setData)
                .catch((reason) => setError(reason.message))
                .finally(() => {
                  setLoading(false);
                  setRetry((value) => value + 1);
                });
            }}
            className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-600"
          >
            Refresh
          </button>
        </div>
      </div>
      {error && (
        <p className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {error}
        </p>
      )}
      {loading && !data && (
        <p className="py-12 text-center text-sm text-slate-400">
          Loading dashboard…
        </p>
      )}
      {data && (
        <div className={loading ? "opacity-60" : ""}>
          <section className="mb-4">
            <h3 className="mb-2 text-xs font-bold uppercase tracking-[.12em] text-slate-400">
              Needs attention
            </h3>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
              {attention.map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => onNavigate(key)}
                  className={`rounded-lg border px-3 py-2 text-left shadow-sm ${attentionClass[attentionTone(key, data.needs_attention[key])]}`}
                >
                  <p className="text-[11px] font-semibold text-slate-500">
                    {label}
                  </p>
                  <p className="mt-0.5 text-xl font-bold">
                    {data.needs_attention[key] ?? "—"}
                  </p>
                </button>
              ))}
            </div>
          </section>
          <div className="grid gap-4 xl:grid-cols-[1.05fr_1.4fr_1fr]">
            <section className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
              <h3 className="text-sm font-bold">Team activity</h3>
              <table className="mt-2 w-full text-xs">
                <thead className="text-left text-slate-400">
                  <tr>
                    <th className="py-1">Operator</th>
                    <th>Orders</th>
                    <th>NDRs</th>
                  </tr>
                </thead>
                <tbody>
                  {data.team_activity.operators.map((row) => (
                    <tr key={row.operator} className="border-t">
                      <td className="py-2 font-semibold">{row.operator}</td>
                      <td>{row.orders_actioned}</td>
                      <td>{row.ndrs_actioned}</td>
                    </tr>
                  ))}
                  <tr className="border-t bg-slate-50 font-bold">
                    <td className="py-2">Team Total</td>
                    <td>{data.team_activity.total.orders_actioned}</td>
                    <td>{data.team_activity.total.ndrs_actioned}</td>
                  </tr>
                </tbody>
              </table>
              <p className="mt-2 text-[10px] text-slate-400">
                Unique records with meaningful timestamped actions.
              </p>
            </section>
            <section className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
              <h3 className="text-sm font-bold">Order summary</h3>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                <Metric
                  label="Total Orders"
                  value={String(data.orders.total)}
                />
                <Metric
                  label="Order Value"
                  value={formatMoney(data.orders.value)}
                />
                <Metric
                  label="Repeat Customer"
                  value={`${data.orders.repeat_percent}%`}
                />
                <Metric label="Actioned" value={String(data.orders.actioned)} />
                <Metric
                  label="Still Pending"
                  value={String(data.orders.pending)}
                />
                <Metric
                  label="Cancelled Excluded"
                  value={String(data.orders.cancelled_excluded)}
                />
              </div>
            </section>
            <section className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
              <h3 className="text-sm font-bold">Payment mix</h3>
              <div className="mt-2 space-y-2">
                {(
                  [
                    ["cod", "COD"],
                    ["prepaid", "Prepaid"],
                    ["partial_cod", "Partial COD"],
                  ] as const
                ).map(([key, label]) => (
                  <div
                    key={key}
                    className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm"
                  >
                    <span className="font-semibold">{label}</span>
                    <span>
                      {data.payment_mix[key].count}{" "}
                      <b className="ml-2">{data.payment_mix[key].percent}%</b>
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </div>
          <section className="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b px-4 py-3">
              <h3 className="text-sm font-bold">Top products</h3>
            </div>
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-400">
                <tr>
                  <th className="px-4 py-2">Product</th>
                  <th>Quantity Ordered</th>
                  <th>Orders</th>
                  <th>Order Value</th>
                </tr>
              </thead>
              <tbody>
                {data.top_products.map((row) => (
                  <tr key={row.product} className="border-t">
                    <td className="px-4 py-2 font-semibold">{row.product}</td>
                    <td>{row.quantity}</td>
                    <td>{row.orders}</td>
                    <td>{formatMoney(row.order_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!data.top_products.length && (
              <p className="p-5 text-center text-sm text-slate-400">
                No products in this period.
              </p>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <p className="text-[10px] font-semibold uppercase text-slate-400">
        {label}
      </p>
      <p className="mt-0.5 text-lg font-bold">{value}</p>
    </div>
  );
}
