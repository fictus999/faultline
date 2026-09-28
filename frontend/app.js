/* Faultline operations console. React without a build step: h() is createElement. */
"use strict";

const { useEffect, useReducer, useRef } = React;
const h = React.createElement;
const HISTORY = 90; // seconds of per-service history kept for the sparklines

const initial = { connected: false, stats: null, alerts: [], history: {}, chaos: {}, webhooks: 0 };

function reducer(state, action) {
  switch (action.type) {
    case "connected":
      return { ...state, connected: action.value };
    case "stats": {
      const history = { ...state.history };
      for (const s of action.stats.services) {
        history[s.service] = [...(history[s.service] || []), s.rate].slice(-HISTORY);
      }
      return { ...state, stats: action.stats, history };
    }
    case "alerts":
      return { ...state, alerts: action.alerts || [] };
    case "chaos":
      return { ...state, chaos: { ...state.chaos, [action.service]: action.errorRate } };
    case "webhook":
      return { ...state, webhooks: state.webhooks + 1 };
    default:
      return state;
  }
}

const pct = (x) => (x == null ? "–" : `${(x * 100).toFixed(1)}%`);
const secondsBetween = (a, b) => (a && b ? ((new Date(b) - new Date(a)) / 1000).toFixed(1) + " s" : null);
const clock = (t) => (t ? new Date(t).toLocaleTimeString() : "");

async function api(path, method, body) {
  const res = await fetch(path, {
    method,
    headers: { "content-type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path}: ${res.status}`);
  return res.json();
}

function useFeed(dispatch) {
  const refreshTimer = useRef(null);
  useEffect(() => {
    let socket;
    let closed = false;
    const refreshAlerts = () => {
      clearTimeout(refreshTimer.current);
      refreshTimer.current = setTimeout(async () => {
        const state = await api("/api/state", "GET");
        dispatch({ type: "alerts", alerts: state.alerts });
      }, 200);
    };
    const connect = () => {
      socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      socket.onopen = () => dispatch({ type: "connected", value: true });
      socket.onclose = () => {
        dispatch({ type: "connected", value: false });
        if (!closed) setTimeout(connect, 1000); // reconnect, then resync from the snapshot
      };
      socket.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.type === "snapshot") {
          if (data.stats) dispatch({ type: "stats", stats: data.stats });
          dispatch({ type: "alerts", alerts: data.alerts });
        } else if (data.type === "stats") {
          dispatch({ type: "stats", stats: data });
        } else if (data.type === "alert_event" || data.type === "delivery") {
          refreshAlerts();
        } else if (data.type === "webhook_received") {
          dispatch({ type: "webhook" });
        } else if (data.type === "chaos") {
          dispatch({ type: "chaos", service: data.service, errorRate: data.error_rate });
        }
      };
    };
    connect();
    return () => {
      closed = true;
      socket && socket.close();
    };
  }, [dispatch]);
}

function Sparkline({ values, baseline }) {
  const w = 220;
  const hgt = 56;
  const top = Math.max(0.05, ...values, baseline || 0);
  const y = (v) => hgt - 4 - (v / top) * (hgt - 8);
  const points = values.map((v, i) => `${(i / (HISTORY - 1)) * w},${y(v)}`).join(" ");
  return h(
    "svg",
    { className: "spark", viewBox: `0 0 ${w} ${hgt}`, preserveAspectRatio: "none" },
    h("line", { x1: 0, x2: w, y1: y(baseline || 0), y2: y(baseline || 0), stroke: "#9da7b3", strokeDasharray: "4 4", strokeWidth: 1 }),
    h("polyline", { points, fill: "none", stroke: "#58a6ff", strokeWidth: 2 })
  );
}

function ServiceTile({ s, history }) {
  const alerting = Boolean(s.severity);
  return h(
    "div",
    { className: `panel tile${alerting ? " alerting" : ""}` },
    h("h3", null, s.service, alerting ? h("span", { className: `badge sev-${s.severity}` }, s.severity) : null),
    h("div", { className: "rate" }, pct(s.rate)),
    h("div", { className: "meta" }, `baseline ${pct(s.baseline)} · z ${s.z} · burn ${s.burn_short}× / ${s.burn_long}×`),
    h(Sparkline, { values: history || [], baseline: s.baseline })
  );
}

function AlertCard({ alert }) {
  const detected = secondsBetween(alert.injected_at, alert.opened_at);
  const mttr = secondsBetween(alert.opened_at, alert.resolved_at);
  const label = alert.status === "RESOLVED" ? "RESOLVED" : alert.severity;
  return h(
    "div",
    { className: "alert" },
    h(
      "div",
      { className: "top" },
      h("span", { className: `badge sev-${label}` }, label),
      h("b", null, `${alert.service} · error rate`),
      h("span", { className: "times" }, `opened ${clock(alert.opened_at)}`),
      detected ? h("span", { className: "times" }, `detected in ${detected}`) : null,
      mttr ? h("span", { className: "times" }, `MTTR ${mttr}`) : null
    ),
    h(
      "ul",
      { className: "events" },
      alert.events.map((e) =>
        h(
          "li",
          { key: e.event_id },
          h("b", null, e.type),
          h("span", { className: `badge sev-${e.type === "RESOLVED" ? "RESOLVED" : e.severity}` }, e.severity),
          h("span", { className: "muted" }, clock(e.created_at)),
          e.deliveries.map((d) =>
            h(
              "span",
              { key: d.sink, className: `chip ${d.status}`, title: d.last_error || "" },
              `${d.sink}: ${d.status}${d.attempts > 1 ? ` (${d.attempts} tries)` : ""}` +
                (d.delivered_at ? ` +${secondsBetween(e.created_at, d.delivered_at)}` : "")
            )
          )
        )
      )
    )
  );
}

function ChaosPanel({ services, chaos }) {
  const [target, setTarget] = React.useState("payments");
  const run = (fn) => fn().catch((err) => alert(err.message));
  return h(
    "div",
    { className: "panel chaos" },
    h("span", { className: "label" }, "Demo controls"),
    h(
      "select",
      { value: target, onChange: (e) => setTarget(e.target.value) },
      (services.length ? services : ["payments"]).map((s) => h("option", { key: s, value: s }, s))
    ),
    h("button", { className: "danger", onClick: () => run(() => api(`/api/chaos/services/${target}`, "POST", { error_rate: 0.35 })) }, "Inject failure (35% errors)"),
    h("button", { onClick: () => run(() => api(`/api/chaos/services/${target}`, "DELETE")) }, "Recover"),
    h("button", { className: "danger", onClick: () => run(() => api("/api/chaos/sinks/webhook", "POST")) }, "Break webhook sink"),
    h("button", { onClick: () => run(() => api("/api/chaos/sinks/webhook", "DELETE")) }, "Heal webhook sink"),
    chaos[target] != null ? h("span", { className: "muted" }, `${target}: injecting ${pct(chaos[target])} errors`) : null
  );
}

function App() {
  const [state, dispatch] = useReducer(reducer, initial);
  useFeed(dispatch);
  const services = state.stats ? state.stats.services : [];
  const firing = state.alerts.filter((a) => a.status === "FIRING").length;
  const lost = services.reduce((n, s) => n + s.lines_lost, 0);
  return h(
    "main",
    null,
    h(
      "header",
      null,
      h("h1", null, "Faultline"),
      h("div", { className: "kpi" }, h("span", null, "Feed"), h("b", null, h("span", { className: "dot", style: { background: state.connected ? "var(--ok)" : "var(--critical)" } }), state.connected ? "live" : "reconnecting")),
      h("div", { className: "kpi" }, h("span", null, "Global error rate (10 s)"), h("b", null, pct(state.stats && state.stats.global_rate))),
      h("div", { className: "kpi" }, h("span", null, "Firing alerts"), h("b", null, firing)),
      h("div", { className: "kpi" }, h("span", null, "Lines lost"), h("b", null, lost)),
      h("div", { className: "kpi" }, h("span", null, "Signed webhooks received"), h("b", null, state.webhooks))
    ),
    h(ChaosPanel, { services: services.map((s) => s.service), chaos: state.chaos }),
    h("div", { className: "grid" }, services.map((s) => h(ServiceTile, { key: s.service, s, history: state.history[s.service] }))),
    h(
      "section",
      { className: "panel alerts" },
      h("h2", null, "Alerts"),
      state.alerts.length ? state.alerts.map((a) => h(AlertCard, { key: a.alert_id, alert: a })) : h("p", { className: "muted" }, "No alerts yet.")
    )
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(h(App));
