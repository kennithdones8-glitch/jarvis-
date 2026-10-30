# Setting up JARVIS on your Mac

Everything here is free. Nothing installs a background service except the two you start yourself
(Ollama and SearXNG), and you can stop both at any time.

## 1. Get the code

From the bundle file:
```bash
git clone ~/Downloads/jarvis.bundle ~/jarvis && cd ~/jarvis
```
Or, once it's on GitHub:
```bash
git clone https://github.com/<you>/jarvis.git ~/jarvis && cd ~/jarvis
```

## 2. Tools

```bash
xcode-select --install                                  # git, compilers (skip if already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"   # Homebrew, if missing
brew install uv ollama
uv sync && uv run pytest                                # expect: all passed, 1 skipped
uv run jarvis init                                      # writes policy.toml and jarvis.toml — read them
mkdir -p ~/Documents/JARVIS/Notes
```

## 3. Local models (Ollama)

```bash
brew services start ollama          # or: ollama serve  (in its own terminal)
ollama pull llama3.2:3b             # ~2 GB, fast everyday model
JARVIS_LIVE_OLLAMA=llama3.2:3b uv run pytest tests/test_live_ollama.py -s
```
The live test prints real tokens/second. **Send me that line.** It decides whether the larger model is usable:
```bash
ollama pull qwen2.5:7b-instruct     # ~4.7 GB, better planner, slower on Intel CPUs
JARVIS_LIVE_OLLAMA=qwen2.5:7b-instruct uv run pytest tests/test_live_ollama.py -s
uv run jarvis models
uv run jarvis ask "In one sentence, who are you?"
```

## 4. Web search (SearXNG in Docker)

Install Docker Desktop (free for personal use), or `brew install colima docker && colima start`.

```bash
mkdir -p ~/.jarvis-searxng
docker run -d --name searxng --restart unless-stopped -p 127.0.0.1:8888:8080 \
  -v ~/.jarvis-searxng:/etc/searxng searxng/searxng
sleep 5 && docker stop searxng
# enable the JSON API that JARVIS uses:
sed -i '' 's/^  formats:$/  formats:\n    - json/' ~/.jarvis-searxng/settings.yml
grep -A3 '^  formats:' ~/.jarvis-searxng/settings.yml     # should list html and json
docker start searxng
curl -s 'http://127.0.0.1:8888/search?q=test&format=json' | head -c 200
```
`-p 127.0.0.1:…` keeps SearXNG reachable only from your Mac.

## 5. Report back

Paste the output of:
```bash
sw_vers; sysctl -n machdep.cpu.brand_string; uv run jarvis models
```
plus the tokens/second lines from step 3.
