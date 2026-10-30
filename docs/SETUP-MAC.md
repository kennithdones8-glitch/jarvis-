# Setting up JARVIS on your Mac

Everything here is free. Nothing installs a background service except Ollama, which you start yourself
and can quit at any time.

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

## 4. Web search (later)

Needs Docker or another way to run SearXNG. Deferred until the core runs on your Mac.

## 5. Report back

Paste the output of `uv run jarvis models` plus the tokens/second lines from step 3.
