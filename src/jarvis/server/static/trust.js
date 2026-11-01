// Trust Contract: built by the server from the live permission engine and settings; this page only shows it.
"use strict";

function h(tag, props, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) if (v !== null && v !== undefined) n.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid instanceof Node ? kid : String(kid));
  return n;
}

const SECTIONS = [
  ["on_its_own", "Does on its own", "own"],
  ["asks_first", "Always asks you first", "asks"],
  ["never", "Never does", "never"],
  ["privacy", "Your data and money", ""],
  ["phone", "Your phone", ""],
];

async function start() {
  const main = document.getElementById("trust");
  try {
    const r = await fetch("/api/trust", { credentials: "same-origin" });
    if (!r.ok) throw new Error(String(r.status));
    const c = await r.json();
    const when = new Date(c.generated).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    main.replaceChildren(
      h("p", { class: "lead" }, `Generated ${when} from JARVIS's current permission rules and settings, so it always matches what is enforced. Change a rule and this page changes with it.`),
      ...SECTIONS.map(([key, title, cls]) => h("section", { class: `panel ${cls}`, "aria-label": title },
        h("header", { class: "ph" }, h("h2", {}, title)),
        c[key].length ? h("ul", {}, c[key].map((l) => h("li", {}, l.text, h("small", {}, l.source))))
                      : h("p", { class: "lead" }, "Nothing."))));
  } catch (e) {
    main.replaceChildren(h("p", { class: "lead" }, `Couldn't load the Trust Contract (${e.message}).`));
  }
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
