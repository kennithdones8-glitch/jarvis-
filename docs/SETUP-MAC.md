# Setting up JARVIS on your Mac

Everything here is free. Nothing runs in the background except Ollama and, if you install it in step 6,
JARVIS's own per-user service (`uv run jarvis service uninstall` removes it).

## 1. Get the code

Clone the repo:
```bash
git clone https://github.com/kennithdones8-glitch/jarvis-.git ~/jarvis
```
If macOS asks to install command line developer tools, accept, then run it again.

## 2. Tools (no Homebrew needed)

Homebrew no longer supports Intel Macs on macOS 14, so use the official installers.
Run each block on its own. Blocks contain no comments, because zsh does not treat a
trailing `# ...` as a comment when you paste it.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Close and reopen Terminal, then:
```bash
cd ~/jarvis
```
```bash
uv sync && uv run pytest
```
```bash
uv run jarvis init
```
```bash
mkdir -p ~/Documents/JARVIS/Notes
```

## 3. Local models (Ollama app)

Download and install the app from https://ollama.com/download (Mac), open it once, then:
```bash
ollama pull llama3.2:3b
```
```bash
JARVIS_LIVE_OLLAMA=llama3.2:3b uv run pytest tests/test_live_ollama.py -s
```
The live test prints real tokens/second. Then try the stronger (slower) planner:
```bash
ollama pull qwen2.5:7b-instruct
```
```bash
JARVIS_LIVE_OLLAMA=qwen2.5:7b-instruct uv run pytest tests/test_live_ollama.py -s
```
```bash
uv run jarvis models
```

## 4. Claude as JARVIS's brain (uses your Claude Pro plan)

Install Claude Code (official installer):
```bash
curl -fsSL https://claude.ai/install.sh | bash
```
Close and reopen Terminal, then sign in once with your Claude Pro account:
```bash
claude
```
After signing in, type `/exit`. Then:
```bash
cd ~/jarvis && uv run jarvis use-claude on
```
It should print `Claude replied: 'JARVIS link online.'`. To go back to local-only: `uv run jarvis use-claude off`.

## 5. Research, memory and documents

```bash
uv run jarvis research "What changed in the latest macOS release?"
```
```bash
uv run jarvis remember "I prefer email over phone calls"
```
```bash
uv run jarvis allow-folder ~/Downloads
```

## 6. Backups and the background service

```bash
uv run jarvis backup now
```
Save the passphrase it prints (password manager). Then:
```bash
uv run jarvis service install
```
```bash
uv run jarvis open
```
Set the Ollama app to launch at login too.

## 7. Touch ID for approvals (optional)

Dashboard → **Systems → Touch ID → Set up Touch ID**. From then on, approvals in the dashboard ask for your
fingerprint. If Touch ID ever stops working:
```bash
uv run jarvis touchid reset --yes
```

## 8. Your iPhone (optional)

Needs iOS 16.4 or later. Free; nothing is exposed to the internet.

1. Install **Tailscale** (free) from the App Store on the Mac and on the iPhone, and sign in to the same
   account on both.
2. In the Tailscale admin console (login.tailscale.com → **DNS**) turn on **MagicDNS** and **HTTPS Certificates**.
3. On the Mac:
```bash
uv run jarvis remote enable
```
4. Open the dashboard on the Mac → **Systems → Phone → Pair a phone**. Scan the code with the iPhone camera,
   tap **Pair with Face ID**.
5. In Safari on the iPhone: Share → **Add to Home Screen**. Open JARVIS from the Home Screen, then
   Systems → **Enable notifications**.

Lost phone: dashboard → Systems → Phone → Remove, or `uv run jarvis devices` then `uv run jarvis devices revoke ID`.
Turn phone access off with `uv run jarvis remote disable`.

## Updating

```bash
uv run jarvis backup now
```
```bash
cd ~/jarvis && git pull && uv sync -q && uv run jarvis service restart
```
To roll back, see "Rolling back" in the README.
