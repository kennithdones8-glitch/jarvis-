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

function say(text, bad) { const m = $("#msg"); m.textContent = text; m.className = `phone-msg${bad ? " bad" : ""}`; }

async function pair(code) {
  const name = $("#devname").value.trim() || "iPhone";
  say("Waiting for Face ID…");
  try {
    const o = await post("/api/pair/options", { code, name });
    const cred = await navigator.credentials.create({ publicKey: {
      ...o, challenge: b64u.toBuf(o.challenge), user: { ...o.user, id: b64u.toBuf(o.user.id) },
      excludeCredentials: o.excludeCredentials.map((c) => ({ ...c, id: b64u.toBuf(c.id) })) } });
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
    const a = await navigator.credentials.get({ publicKey: {
      challenge: b64u.toBuf(o.challenge), rpId: o.rpId, timeout: o.timeout, userVerification: o.userVerification,
      allowCredentials: o.allowCredentials.map((c) => ({ ...c, id: b64u.toBuf(c.id) })) } });
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
