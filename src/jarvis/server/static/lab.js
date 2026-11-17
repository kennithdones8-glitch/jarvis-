"use strict";
// The Self-Evolution Laboratory (Evolution 4.0, Stage 5), part of the Evolution page. Everything shown comes from
// /api/evolution and the experiments already listed by /api/learn: opportunities with the numbers behind their
// ranking, experiment designs, improvement packages with their evidence and status, and the append-only history.
// Nothing is drawn for effect, and nothing here can change JARVIS: packages give you the command to apply or roll
// back yourself. Uses the page's helpers (h, api, call, fill, $, plural, note, ask, cancelled, onPhone) from app.js.
(function (root) {
  const state = { q: "", designs: {} };
  const day = (iso) => (iso || "").slice(0, 16).replace("T", " ");
  const VERDICT = { holds: "held in every run", flaky: "no verdict (flaky)", fails: "failed", "did not run": "did not run" };
  const KIND = { opportunity: "Opportunity", design: "Design", experiment: "Experiment", package: "Package", decision: "Your decision",
                 applied: "Applied by you", rolled_back: "Rolled back by you" };

  async function post(path, body) {
    try { return await call(path, body); } catch (e) { note(e.name === "NotAllowedError" ? cancelled(e) : `Laboratory: ${e.message}`); return null; }
  }

  function designBox(d) {
    const list = (title, items) => h("div", {}, h("b", {}, title), h("ul", {}, items.map((x) => h("li", {}, x))));
    return h("div", { class: "lab-design" },
      h("p", {}, h("b", {}, "Problem: "), d.problem), list("Evidence", d.evidence), h("p", {}, h("b", {}, "Proposed: "), d.proposed),
      list("Alternatives", d.alternatives), list("Success means", d.success), list("What could regress", d.regression_risks),
      list("Test plan", d.test_plan),
      h("p", {}, h("b", {}, "Budget: "), `${plural(d.budget.runs, "run")} per side · ${Math.round(d.budget.time_limit_s_per_run / 60)} min limit each · network: ${d.budget.network} · ${d.budget.cost}`),
      h("p", {}, h("b", {}, "Roll back: "), d.rollback), h("p", { class: "hl-sub" }, `Needs: ${d.needs}.`));
  }

  function opportunity(o, maxRuns) {
    const d = state.designs[o.subject];
    const runs = Math.min(3, maxRuns);
    return h("li", { class: "lab-opp" },
      h("b", {}, o.title), h("div", {}, o.problem),
      h("small", {}, `Benefit ${o.benefit}/5 · confidence ${Math.round(o.confidence * 100)}% · complexity ${o.complexity}/4 · risk ${o.risk}/3 · reversible: ${o.reversible}`),
      h("small", { title: o.how }, `Priority ${o.priority} — ${o.how}`),
      o.tried_before.length ? h("small", {}, `Tried before: ${o.tried_before.map((t) => `${VERDICT[t.verdict] || t.verdict} (${day(t.ts)})`).join("; ")}. An attempt that failed is not proof the idea is wrong.`) : null,
      o.last_decision ? h("small", {}, `Your last decision on a package for this: ${o.last_decision}.`) : null,
      onPhone() ? null : h("div", { class: "row" },
        h("button", { class: "btn btn-ghost btn-xs", type: "button", onclick: async () => {
          const r = await post("/api/evolution/design", { subject: o.subject, runs });
          if (r) { state.designs[o.subject] = r; load(true); }
        } }, d ? "Design again" : "Design an experiment"),
        d && d.testable_in_lab ? h("button", { class: "btn btn-ghost btn-xs", type: "button",
          title: "JARVIS writes a patch, tests it in the sandbox against your current code, and never applies it. Needs autonomy level 6.",
          onclick: async () => {
            if (!(await ask(`Draft a fix for “${o.title}” and test it ${runs} times in the sandbox?\n\nThis can take a long time on this Mac. Nothing is applied.`, { ok: "Draft and test" }))) return;
            if (await post("/api/experiments", { kind: "draft", problem: o.problem, runs, opportunity: o.subject })) { note("Experiment started. It appears under Experiments when it finishes."); }
          } }, `Draft a fix and test it ×${runs}`) : null),
      d ? designBox(d) : null);
  }

  function pkg(p) {
    const b = p.body, ev = b.evidence || {};
    const act = async (path, body) => { if (await post(path, { package: p.seq, ...body })) load(true); };
    return h("li", { class: `lab-pkg ${p.status.replace(/ /g, "-")}` },
      h("div", { class: "l-head" }, h("span", { class: "l-kind" }, p.status), h("span", { class: "l-when" }, day(p.ts))),
      h("b", {}, p.title),
      h("small", {}, `Evidence: ${VERDICT[ev.verdict] || ev.verdict} · ${plural(ev.runs || 0, "run")} · tests passed per run ${(ev.tests_passed_per_run || []).join(", ")}`
        + ((ev.tests_fixed_in_every_run || []).length ? ` · fixes ${plural(ev.tests_fixed_in_every_run.length, "test")} every time` : "") + ` · ${(ev.isolation || []).join(", ")}`),
      h("small", {}, `Files: ${(b.files || []).join(", ") || "see the experiment"} · ${b.migration}`),
      h("small", { class: (b.security.touches_security_sensitive_files || []).length ? "lab-warn" : null }, `Security: ${b.security.note}`),
      onPhone() ? null : h("div", { class: "row" },
        p.status === "awaiting your decision" ? [
          h("button", { class: "btn btn-sm", type: "button", onclick: () => act("/api/evolution/decide", { decision: "approved" }) }, "Approve"),
          h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => act("/api/evolution/decide", { decision: "rejected" }) }, "Reject")] : null,
        p.status === "approved" ? h("button", { class: "btn btn-ghost btn-sm", type: "button", title: "Record that you applied it yourself (JARVIS never applies anything)",
          onclick: () => act("/api/evolution/mark", { what: "applied" }) }, "I applied it") : null,
        p.status === "applied" ? h("button", { class: "btn btn-ghost btn-sm", type: "button", title: "Record that you rolled it back yourself",
          onclick: () => act("/api/evolution/mark", { what: "rolled_back" }) }, "I rolled it back") : null),
      p.status === "approved" ? h("small", {}, "Approving changes nothing by itself. Open the experiment for the command to apply it yourself.") : null);
  }

  async function load() {
    const el = $("#lab");
    if (!el) return;
    let d;
    try { d = await api(`/api/evolution?q=${encodeURIComponent(state.q)}`); } catch (e) { fill(el, h("p", { class: "empty" }, `Laboratory: ${e.message}`)); return; }
    const exps = ((typeof ui !== "undefined" && ui.evo && ui.evo.experiments) || []).filter((x) => x.state === "done" && x.results && x.results.evaluation
      && x.results.evaluation.verdict === "holds" && !d.packages.some((p) => p.body.experiment === x.id));
    const search = h("input", { type: "search", class: "lab-q", placeholder: "Search the history…", "aria-label": "Search the evolution history", value: state.q });
    search.addEventListener("change", () => { state.q = search.value; load(true); });
    fill(el,
      h("h3", { class: "sys-part" }, "Laboratory"),
      h("p", { class: "hl-sub" }, "JARVIS finds what's weak, designs a fair test, and judges it on repeated runs in the sandbox. A change that holds becomes a package for you to approve. JARVIS never applies, merges or pushes anything."),
      h("h3", { class: "sys-part" }, `Opportunities (${d.opportunities.length})`),
      d.opportunities.length ? h("ul", { class: "lab-list" }, d.opportunities.map((o) => opportunity(o, d.max_runs)))
        : h("div", { class: "empty" }, "Nothing in the evidence calls for a change right now."),
      exps.length ? [h("h3", { class: "sys-part" }, "Held in the lab, no package yet"),
        h("ul", { class: "lab-list" }, exps.map((x) => h("li", {}, h("b", {}, x.objective),
          onPhone() ? null : h("button", { class: "btn btn-ghost btn-xs", type: "button", onclick: async () => { if (await post("/api/evolution/package", { experiment: x.id })) load(true); } }, "Open a package"))))] : null,
      h("h3", { class: "sys-part" }, `Improvement packages (${d.packages.length})`),
      d.packages.length ? h("ul", { class: "lab-list" }, d.packages.map(pkg)) : h("div", { class: "empty" }, "No packages yet. One is made from an experiment that held in every run."),
      h("h3", { class: "sys-part" }, "History"), search,
      d.history.length ? h("ul", { class: "lab-history" }, d.history.map((x) => h("li", {},
        h("span", { class: "l-when" }, day(x.ts)), " ", h("b", {}, `${KIND[x.kind] || x.kind}: `), x.title.replace(/^(Package|Design): /, ""),
        x.kind === "experiment" && x.body.why ? h("small", {}, ` — ${x.body.why}`) : null)))
        : h("div", { class: "empty" }, state.q ? "Nothing in the history matches." : "Nothing recorded yet."),
      h("p", { class: "hl-sub" }, "The history can be added to but never changed or deleted, including failed and rejected attempts."));
  }

  root.JarvisLab = { load };
})(window);
