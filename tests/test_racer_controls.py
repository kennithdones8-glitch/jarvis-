"""Kerbside Grand Prix controls, in a real browser (skipped when Playwright isn't installed): the Controls settings
(sensitivity, touch steering, pedals left or right, large buttons, auto-accelerate) change the touch layout, tilt
steering follows the phone (centred on the grid), and every race shows a rev meter for the launch."""

import json
import shutil
import subprocess

import pytest

from jarvis.server.app import STATIC

NODE = shutil.which("node")
ROOT = STATIC.parents[3]

BROWSER = r"""
const { chromium, devices } = require(process.env.PW || 'playwright');
(async () => {
  const b = await chromium.launch(); const errs = [], out = {};
  const p = await (await b.newContext({ ...devices['iPhone 13'] })).newPage(); p.on('pageerror', (e) => errs.push(e.message));
  // the person taps "Allow" when asked for motion access (the browser alone would say no)
  await p.addInitScript(() => { if (window.DeviceOrientationEvent) window.DeviceOrientationEvent.requestPermission = () => Promise.resolve('granted'); });
  await p.goto('file://' + process.argv[2]); await p.waitForTimeout(500);
  const tilt = (gamma) => p.evaluate((g) => window.dispatchEvent(new DeviceOrientationEvent('deviceorientation', { alpha: 0, beta: 30, gamma: g })), gamma);
  // Settings → Controls
  await p.getByRole('button', { name: 'Settings', exact: true }).click(); await p.waitForTimeout(300);
  out.fields = await p.evaluate(() => ['s-sens', 's-touch', 's-side', 's-size'].map((id) => !!document.getElementById(id)));
  await p.selectOption('#s-side', 'left'); await p.selectOption('#s-size', 'large');
  const feed = setInterval(() => tilt(0).catch(() => {}), 50);                 // the phone's sensor, held level
  await p.selectOption('#s-touch', 'tilt'); await p.waitForTimeout(1200);
  out.touch = await p.evaluate(() => document.getElementById('s-touch').value);
  out.toast = await p.evaluate(() => [...document.querySelectorAll('.race-toast')].map((t) => t.textContent).join(' | '));
  out.saved = await p.evaluate(() => { const s = JSON.parse(localStorage.getItem('kerbside-save-v3')).settings; return [s.padSide, s.padSize, s.touchSteer]; });
  // a race: the launch meter on the grid, the tilt centred there, then steering with the phone
  await p.evaluate(() => { const V = window.JarvisRacer.view; V.overlay(null); V.start({ track: 'harbour', time: 'day', weather: 'dry', mode: 'circuit', laps: 3, field: [{ id: 'a', code: 'AAA', name: 'A', color: '#2f7de1', shape: 'super' }] }, {}); });
  await p.waitForTimeout(800);
  out.grid = await p.evaluate(() => { const m = document.querySelector('.race-modebox'); return [!m.hidden, m.textContent.includes('launch')]; });
  out.pads = await p.evaluate(() => { const pads = document.querySelector('.race-pads'), r = (k) => pads.querySelector(`[data-k="${k}"]`).getBoundingClientRect();
    return { cls: [...pads.classList], arrows: getComputedStyle(pads.querySelector('[data-k="left"]')).display, gasLeftOfBrake: r('up').left < window.innerWidth / 2 }; });
  clearInterval(feed);
  await p.waitForFunction(() => window.JarvisRacer.view.race.state === 'race', null, { timeout: 20000 });
  for (let i = 0; i < 12; i++) { await tilt(12); await p.waitForTimeout(50); }
  out.steer = await p.evaluate(() => window.JarvisRacer.view.race.cars[0].steerIn);
  for (let i = 0; i < 12; i++) { await tilt(-40); await p.waitForTimeout(50); }
  out.full = await p.evaluate(() => window.JarvisRacer.view.race.cars[0].steerIn);
  console.log(JSON.stringify({ ...out, errs })); await b.close();
})();
"""


def test_controls_tilt_and_launch_in_a_real_browser(tmp_path):
    if not NODE:
        pytest.skip("node not installed")
    if subprocess.run([NODE, "-e", "require.resolve('playwright')"], capture_output=True).returncode:
        pytest.skip("Playwright isn't installed (browser checks are optional)")
    site = tmp_path / "site"
    site.mkdir()
    shutil.copy(ROOT / "games/kerbside/index.html", site / "index.html")
    for f in STATIC.glob("racer*"):
        shutil.copy(f, site / f.name)
    shutil.copytree(STATIC / "fonts", site / "fonts")
    script = tmp_path / "check.js"
    script.write_text(BROWSER)
    out = subprocess.run([NODE, str(script), str(site / "index.html")], capture_output=True, text=True, timeout=300, cwd=tmp_path)
    assert out.returncode == 0, out.stderr[-2000:]
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["errs"] == [], r["errs"]
    assert r["fields"] == [True, True, True, True]
    assert r["touch"] == "tilt" and "Tilt steering on" in r["toast"] and r["saved"] == ["left", "large", "tilt"]
    assert r["grid"] == [True, True]                                            # the rev meter on the grid
    assert {"left", "large", "tilt"} <= set(r["pads"]["cls"]) and r["pads"]["arrows"] == "none" and r["pads"]["gasLeftOfBrake"]
    assert 0.35 < r["steer"] < 0.75 and r["full"] < -0.95                      # 12° of 24° is about half lock; 40° is full
