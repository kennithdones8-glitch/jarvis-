"use strict";
// Pairing and Face ID sign-in for the iPhone companion. Passkeys never leave the phone; JARVIS only
// receives signed responses, which it verifies on the Mac.
const $ = (s) => document.querySelector(s);
const b64u = {
  toBuf: (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0)).buffer,
  fromBuf: (b) => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
};

async function post(path, body) {
  const r = await fetch(path, { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-By": "jarvis" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

// iPhone Safari before iOS 17.4 only shows Face ID when it's called straight from a tap, and we fetch a
// challenge first. If Safari refuses at once, ask for one more tap and call it again from inside that tap.
async function withTap(op, label) {
  const t0 = Date.now();
  try { return await op(); } catch (e) {
    if (e.name !== "NotAllowedError" || Date.now() - t0 > 1500) throw e;
    return new Promise((resolve, reject) => {
      const dlg = document.createElement("dialog");
      dlg.className = "pairdlg";
      const title = document.createElement("h2");
      title.textContent = label;
      const msg = document.createElement("p");
      msg.className = "hl-sub";
      msg.textContent = "Your iPhone needs one more tap to show Face ID.";
      const go = document.createElement("button");
      go.className = "btn btn-approve phone-btn";
      go.type = "button";
      go.textContent = label;
      const cancel = document.createElement("button");
      cancel.className = "btn phone-btn";
      cancel.type = "button";
      cancel.textContent = "Cancel";
      const done = () => { dlg.close(); dlg.remove(); };
      go.addEventListener("click", () => { done(); op().then(resolve, reject); });
      cancel.addEventListener("click", () => { done(); reject(e); });
      dlg.append(title, msg, go, cancel);
      document.body.append(dlg);
      dlg.showModal();
    });
  }
}

function say(text, bad) { const m = $("#msg"); m.textContent = text; m.className = `phone-msg${bad ? " bad" : ""}`; }

async function pair(code) {
  const name = $("#devname").value.trim() || "iPhone";
  say("Waiting for Face ID…");
  try {
    const o = await post("/api/pair/options", { code, name });
    const cred = await withTap(() => navigator.credentials.create({ publicKey: {
      ...o, challenge: b64u.toBuf(o.challenge), user: { ...o.user, id: b64u.toBuf(o.user.id) },
      excludeCredentials: o.excludeCredentials.map((c) => ({ ...c, id: b64u.toBuf(c.id) })) } }), "Pair with Face ID");
    await post("/api/pair/finish", { code, name, credential: {
      id: cred.id, rawId: b64u.fromBuf(cred.rawId), type: cred.type,
      response: { clientDataJSON: b64u.fromBuf(cred.response.clientDataJSON),
                  attestationObject: b64u.fromBuf(cred.response.attestationObject) } } });
    say("Paired. Opening JARVIS…");
    location.replace("/");
  } catch (e) { say(e.name === "NotAllowedError" ? "Face ID was cancelled." : e.message, true); }
}

async function login() {
  say("Waiting for Face ID…");
  try {
    const o = await post("/api/login/options", {});
    const a = await withTap(() => navigator.credentials.get({ publicKey: {
      challenge: b64u.toBuf(o.challenge), rpId: o.rpId, timeout: o.timeout, userVerification: o.userVerification,
      allowCredentials: o.allowCredentials.map((c) => ({ ...c, id: b64u.toBuf(c.id) })) } }), "Sign in with Face ID");
    await post("/api/login/finish", { challengeId: o.challengeId, credential: {
      id: a.id, rawId: b64u.fromBuf(a.rawId), type: a.type,
      response: { clientDataJSON: b64u.fromBuf(a.response.clientDataJSON),
                  authenticatorData: b64u.fromBuf(a.response.authenticatorData),
                  signature: b64u.fromBuf(a.response.signature) } } });
    location.replace("/");
  } catch (e) { say(e.name === "NotAllowedError" ? "Face ID was cancelled." : e.message, true); }
}

document.addEventListener("DOMContentLoaded", () => {
  if (!window.PublicKeyCredential) { say("This browser can't use passkeys. Use Safari on iOS 16 or later.", true); return; }
  const code = new URLSearchParams(location.search).get("pair");
  if (code) {
    $("#pair").hidden = false;
    $("#pairbtn").addEventListener("click", () => pair(code));
  } else {
    $("#login").hidden = false;
    $("#loginbtn").addEventListener("click", login);
  }
});
