import { useEffect, useState } from "react";
import { formatMoney } from "../services/orders";
import {
  analyticsKpis as KPI,
  getAnalytics,
  type AnalyticsData,
} from "../services/analytics";
import { PeriodSelector, type PeriodPreset } from "./PeriodSelector";
import { TrackingPollerHealth } from "./TrackingPollerHealth";
import {
  cancellationTone,
  deltaTone,
  kpiComparisonTone,
  semanticTextClass,
} from "../utils/semanticFormatting";

const value = (amount: number, kind: string) =>
  kind === "money"
    ? formatMoney(amount)
    : kind === "rate"
      ? `${amount}%`
      : String(amount);
const compare = (data: AnalyticsData, key: string) => {
  const item = data.comparisons[key];
  if (!item) return <span className="text-slate-500">—</span>;
  const text =
    item.points != null
      ? `${item.points >= 0 ? "+" : ""}${item.points} pp`
      : item.percent == null
        ? `${item.absolute >= 0 ? "+" : ""}${item.absolute}`
        : `${item.percent >= 0 ? "+" : ""}${item.percent}%`;
  return (
    <span className={semanticTextClass[kpiComparisonTone(key, item)]}>
      {text}
    </span>
  );
};

export function AnalyticsPage({ showDiagnostics = false }: { showDiagnostics?: boolean }) {
  const today = new Date().toISOString().slice(0, 10);
  const [preset, setPreset] = useState<PeriodPreset>("last_30_days");
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const [payment, setPayment] = useState("all");
  const [customer, setCustomer] = useState("all");
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    void getAnalytics(preset, start, end, payment, customer)
      .then((result) => {
        if (!active) return;
        setData(result);
        setError(result.refresh_error || "");
        if (result.refreshing)
          timer = window.setTimeout(() => setRetry((v) => v + 1), 5000);
      })
      .catch((reason) => {
        if (!active) return;
        setError(reason.message);
        if (String(reason.message).includes("preparing"))
          timer = window.setTimeout(() => setRetry((v) => v + 1), 3000);
      });
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [preset, start, end, payment, customer, retry]);
  return (
    <div>
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-orange-600">Analytics</p>
          <h2 className="text-2xl font-bold">Business performance</h2>
          <p className="text-xs text-slate-500">
            {data?.period.label || "Last 30 Days"}
            {data?.last_refreshed_at
              ? ` · Refreshed ${new Date(data.last_refreshed_at).toLocaleString("en-IN")}`
              : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <PeriodSelector
            prefix="Analytics"
            preset={preset}
            start={start}
            end={end}
            onChange={(p, f, t) => {
              setPreset(p);
              setStart(f);
              setEnd(t);
            }}
          />
          <select
            aria-label="Analytics payment type"
            value={payment}
            onChange={(e) => setPayment(e.target.value)}
            className="rounded-md border px-2 text-xs"
          >
            <option value="all">All payments</option>
            <option value="cod">COD</option>
            <option value="prepaid">Prepaid</option>
            <option value="partial_cod">Partial COD</option>
          </select>
          <select
            aria-label="Analytics customer type"
            value={customer}
            onChange={(e) => setCustomer(e.target.value)}
            className="rounded-md border px-2 text-xs"
          >
            <option value="all">All customers</option>
            <option value="new">New</option>
            <option value="repeat">Repeat</option>
          </select>
          <button
            onClick={() =>
              void getAnalytics(preset, start, end, payment, customer, true)
                .then(setData)
                .finally(() => setRetry((v) => v + 1))
            }
            className="rounded-md border px-2.5 text-xs font-semibold"
          >
            Refresh
          </button>
        </div>
      </header>
      {error && (
        <p className="mb-3 rounded-lg bg-amber-50 p-2 text-xs text-amber-800">
          {error}
        </p>
      )}
      {data && (
        <>
          <section>
            <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">
              Business Performance
            </h3>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-9">
              {KPI.map(([key, label, kind]) => (
                <div key={key} className="rounded-lg border bg-white p-2.5">
                  <p className="text-[10px] font-semibold text-slate-400">
                    {label}
                  </p>
                  <p className="text-lg font-bold">
                    {value(data.business[key], kind)}
                  </p>
                  <p className="text-[10px]">
                    {compare(data, key)} vs previous
                  </p>
                </div>
              ))}
            </div>
          </section>
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <section className="rounded-xl border bg-white p-3">
              <h3 className="text-sm font-bold">Customer Performance</h3>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs md:grid-cols-3">
                {[
                  ["New Customers", "new_customers"],
                  ["Repeat Customers", "repeat_customers"],
                  ["New Revenue", "new_revenue"],
                  ["Repeat Revenue", "repeat_revenue"],
                  ["AOV: New", "new_aov"],
                  ["AOV: Repeat", "repeat_aov"],
                ].map(([label, key]) => (
                  <div key={key} className="rounded bg-slate-50 p-2">
                    <p className="text-slate-400">{label}</p>
                    <b>
                      {key.includes("revenue") || key.includes("aov")
                        ? formatMoney(data.customers[key])
                        : data.customers[key]}
                    </b>
                  </div>
                ))}
              </div>
            </section>
            <section className="rounded-xl border bg-white p-3">
              <h3 className="text-sm font-bold">Payment Mix</h3>
              <table className="mt-2 w-full text-xs">
                <thead>
                  <tr className="text-left text-slate-400">
                    <th>Type</th>
                    <th>Orders</th>
                    <th>Mix</th>
                    <th>Value</th>
                    <th>AOV</th>
                    <th>Cancel</th>
                  </tr>
                </thead>
                <tbody>
                  {data.payment.map((row) => (
                    <tr key={row.key} className="border-t">
                      <td className="py-2 font-semibold">{row.label}</td>
                      <td>{row.orders}</td>
                      <td>{row.percent}%</td>
                      <td>{formatMoney(row.value)}</td>
                      <td>{formatMoney(row.aov)}</td>
                      <td
                        className={`font-semibold ${semanticTextClass[cancellationTone(row.cancellation_percent)]}`}
                      >
                        {row.cancellation_percent}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>
          <section className="mt-4 overflow-x-auto rounded-xl border bg-white">
            <h3 className="p-3 text-sm font-bold">Product Performance</h3>
            <table className="w-full min-w-[900px] text-xs">
              <thead className="bg-slate-50 text-left text-slate-400">
                <tr>
                  <th className="p-2">Product</th>
                  <th>Qty</th>
                  <th>Orders</th>
                  <th>Value</th>
                  <th>Order %</th>
                  <th>New</th>
                  <th>Repeat</th>
                  <th>Δ Qty</th>
                  <th>Δ Orders</th>
                  <th>Δ Value</th>
                </tr>
              </thead>
              <tbody>
                {data.products.map((row) => (
                  <tr key={row.product} className="border-t">
                    <td className="p-2 font-semibold">{row.product}</td>
                    <td>{row.quantity}</td>
                    <td>{row.orders}</td>
                    <td>{formatMoney(row.value)}</td>
                    <td>{row.order_percent}%</td>
                    <td>{row.new_orders}</td>
                    <td>{row.repeat_orders}</td>
                    <td className={semanticTextClass[deltaTone(row.quantity_change)]}>
                      {row.quantity_change}
                    </td>
                    <td className={semanticTextClass[deltaTone(row.order_change)]}>
                      {row.order_change}
                    </td>
                    <td className={semanticTextClass[deltaTone(row.value_change)]}>
                      {formatMoney(row.value_change)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
          <Trend data={data} />
        </>
      )}
      {showDiagnostics && <TrackingPollerHealth />}
    </div>
  );
}

function Trend({ data }: { data: AnalyticsData }) {
  const points = data.trend.points;
  const max = Math.max(...points.map((p) => p.revenue), 1);
  return (
    <section className="mt-4 rounded-xl border bg-white p-3">
      <h3 className="text-sm font-bold">
        Orders and Revenue Trend{" "}
        <span className="font-normal text-slate-400">
          ({data.trend.granularity})
        </span>
      </h3>
      <div className="mt-3 flex h-32 items-end gap-1 overflow-x-auto">
        {points.map((point) => (
          <div
            key={point.label}
            title={`${point.label}: ${point.orders} orders, ${formatMoney(point.revenue)}`}
            className="flex min-w-5 flex-1 flex-col items-center justify-end"
          >
            <span className="text-[9px] text-slate-500">{point.orders}</span>
            <div
              className="w-full rounded-t bg-orange-400"
              style={{ height: `${Math.max((point.revenue * 90) / max, 2)}px` }}
            />
            <span className="mt-1 max-w-14 truncate text-[8px] text-slate-400">
              {point.label.slice(-5)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
