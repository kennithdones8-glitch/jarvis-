// Benchmark history (read-only): runs, one run's tasks and failures, before/after under the merge rule.
"use strict";

const $ = (id) => document.getElementById(id);
function h(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid instanceof Node ? kid : String(kid));
  return n;
}
async function api(path) {
  const r = await fetch(path, { credentials: "same-origin" });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${r.status}`);
  return data;
}
const when = (iso) => { try { return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); } catch (e) { return iso; } };
const label = (s) => `${when(s.started)} · ${s.version || "?"}${s.commit ? " (" + s.commit + ")" : ""}${s.coding_self_test ? " · self-test" : ""}`;
const pct = (p, n) => (n ? Math.round((100 * p) / n) : 0);

let RUNS = [];
// replaceChildren with nested lists and optional parts (null) flattened out, as h() does.
const fill = (box, ...kids) => box.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
// The page's CSP forbids inline style attributes; setting the property from script is allowed.
const width = (el, p) => { el.style.width = `${p}%`; return el; };

function bars(categories) {
  return h("div", { class: "bars" }, Object.entries(categories).map(([cat, c]) =>
    h("div", { class: "bar" }, h("span", {}, cat.replace("_", " ")),
      h("div", { class: "track" }, width(h("div", { class: `fill${c.passed === c.scored ? " full" : ""}` }), pct(c.passed, c.scored))),
      h("span", {}, `${c.passed}/${c.scored}`))));
}

function runCard(s) {
  return h("button", { type: "button", class: "run-card", "data-run": s.run_id, onclick: () => showRun(s.run_id) },
    h("div", { class: "run-head" }, h("b", {}, `${s.passed} / ${s.scored} runs passed`),
      h("span", { class: "run-meta" }, `${s.models} · ×${s.repeat}${s.skipped ? ` · ${s.skipped} skipped` : ""}`)),
    h("div", { class: "run-meta" }, label(s)),
    bars(s.categories));
}

async function showRun(id) {
  document.querySelectorAll(".run-card").forEach((c) => c.setAttribute("aria-current", String(c.dataset.run === id)));
  const panel = $("runpanel"), box = $("run");
  panel.hidden = false;
  box.replaceChildren(h("p", { class: "b-muted" }, "Loading…"));
  try {
    const d = await api(`/api/bench/${encodeURIComponent(id)}`);
    const fails = d.tasks.filter((t) => t.failure);
    $("run-h").textContent = `Run · ${when(d.summary.started)}`;
    fill(box,
      h("div", { class: "b-nums" }, h("span", {}, h("b", {}, `${d.summary.passed}/${d.summary.scored}`), " runs passed"),
        h("span", {}, h("b", {}, String(d.summary.claude_calls)), " Claude calls"),
        h("span", {}, `JARVIS ${d.summary.version || "?"}`)),
      h("table", { class: "b-table" },
        h("thead", {}, h("tr", {}, h("th", {}, "Task"), h("th", {}, "Category"), h("th", { class: "n" }, "Passed"), h("th", { class: "n" }, "Avg s"))),
        h("tbody", {}, d.tasks.map((t) => h("tr", {},
          h("td", {}, t.id), h("td", {}, t.category.replace("_", " ")),
          h("td", { class: "n" }, t.scored ? `${t.passed}/${t.scored}` : "skipped"),
          h("td", { class: "n" }, t.avg_seconds ?? "–"))))),
      fails.length ? h("h3", { class: "b-muted" }, `Failures (${fails.length} task${fails.length > 1 ? "s" : ""}, first failed run of each)`)
                   : h("p", { class: "b-muted" }, "No failures."),
      fails.map(failure));
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    box.replaceChildren(h("p", { class: "b-muted" }, `Couldn't load this run: ${e.message}`));
  }
}

function failure(t) {
  const f = t.failure;
  return h("details", { class: "fail" },
    h("summary", {}, h("b", {}, t.id), h("span", { class: "b-muted" }, `passed ${t.passed}/${t.scored}`)),
    h("div", { class: "fx" },
      f.failed.map((x) => h("div", { class: "bad" }, `✗ ${x}`)),
      f.error ? h("div", { class: "bad" }, `error: ${f.error}`) : null,
      (f.checked.length || f.lookup_notes.length) ? h("div", {}, `Looked up: ${f.checked.join(", ") || "nothing"}${f.lookup_notes.length ? " (" + f.lookup_notes.join("; ") + ")" : ""}`) : null,
      f.approvals.length ? h("div", {}, "Approvals: " + f.approvals.map((a) => `${a.call} “${a.summary}” → ${a.approved ? "approved" : "rejected"}`).join("; ")) : null,
      f.plan_kind && f.plan_kind !== "plan" ? h("div", {}, `Plan: ${f.plan_kind}`) : null,
      h("pre", {}, f.answer || "(no answer)")));
}

async function showCompare() {
  const box = $("compare"), before = $("before").value, after = $("after").value;
  if (!before || !after) { box.replaceChildren(h("p", { class: "b-muted" }, "Needs at least two runs.")); return; }
  box.replaceChildren(h("p", { class: "b-muted" }, "Comparing…"));
  try {
    const c = await api(`/api/bench/compare?before=${encodeURIComponent(before)}&after=${encodeURIComponent(after)}`);
    const pb = c.rows.filter((r) => r.was).length, pa = c.rows.filter((r) => r.now).length;
    fill(box,
      h("div", { class: `verdict ${c.merge ? "ok" : "no"}` },
        h("strong", {}, c.merge ? "Meets the merge rule" : "Doesn't meet the merge rule"),
        c.reasons.length ? h("ul", {}, c.reasons.map((r) => h("li", {}, r))) : null),
      h("div", { class: "b-nums" },
        h("span", {}, "Tasks passing ", h("b", {}, `${pb} → ${pa}`), ` of ${c.rows.length}`),
        h("span", {}, "Net ", h("b", {}, (c.net > 0 ? "+" : "") + c.net)),
        h("span", {}, "Claude calls ", h("b", {}, `${c.claude[0]} → ${c.claude[1]}`))),
      h("table", { class: "b-table" },
        h("thead", {}, h("tr", {}, h("th", {}, "Task"), h("th", { class: "n" }, "Before"), h("th", { class: "n" }, "After"), h("th", {}, ""))),
        h("tbody", {}, c.rows.map((r) => h("tr", {}, h("td", {}, r.id), h("td", { class: "n" }, r.before), h("td", { class: "n" }, r.after),
          h("td", {}, r.now && !r.was ? h("span", { class: "tag-fixed" }, "fixed") : r.was && !r.now ? h("span", { class: "tag-broke" }, "new failure") : ""))))),
      c.left_out.length ? h("p", { class: "b-muted" }, "Left out: " + c.left_out.join("; ")) : null,
      h("p", { class: "b-muted" }, "A task passes when more than half its runs pass. Rule: at least +2 tasks, no new failures, Claude calls up at most 25%, no unapproved changes."));
  } catch (e) {
    box.replaceChildren(h("p", { class: "b-muted" }, `Couldn't compare: ${e.message}`));
  }
}

async function start() {
  try {
    RUNS = (await api("/api/bench")).runs;
  } catch (e) {
    $("runs").replaceChildren(h("p", { class: "b-muted" }, `Couldn't load benchmarks: ${e.message}`));
    $("compare").replaceChildren();
    return;
  }
  $("runcount").textContent = RUNS.length ? String(RUNS.length) : "";
  $("runs").replaceChildren(...(RUNS.length ? RUNS.map(runCard)
    : [h("p", { class: "b-muted" }, "No benchmark runs yet. On the Mac: uv run jarvis bench run")]));
  const opts = (sel) => RUNS.map((s) => h("option", { value: s.run_id, selected: sel === s.run_id ? true : null },
    `${s.passed}/${s.scored} · ${label(s)}`));
  $("before").replaceChildren(...opts(RUNS[1] && RUNS[1].run_id));
  $("after").replaceChildren(...opts(RUNS[0] && RUNS[0].run_id));
  $("before").addEventListener("change", showCompare);
  $("after").addEventListener("change", showCompare);
  showCompare();
}
start();

// Emergency stop on this page too: one tap, never asks — the same request the dashboard sends.
(() => {
  const b = document.getElementById("estop");
  if (!b) return;
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const r = await fetch("/api/stop", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-By": "jarvis" },
        body: JSON.stringify({ reason: "stopped from the dashboard" }) });
      b.textContent = r.ok ? "Stopped · release it on Home" : "Stop failed · use Home";
    } catch (e) {
      b.textContent = "Stop failed · use Home";
    }
  });
})();
