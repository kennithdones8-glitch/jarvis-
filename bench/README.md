# JARVIS benchmark

Fixed tasks with checks written before any run, so JARVIS can be compared fairly with the standalone Claude app
and with earlier versions of itself. Milestone 1: 12 core tasks across reasoning, coding, research, memory,
planning, tool use and recovery.

## Two sets

- **core** (12 tasks, the default): fixed, and the ones compared with the Claude-app baseline. They don't change.
- **extended** (12 more): extra coding, research, memory, planning, tool-use and recovery coverage.
  `jarvis bench run --set extended` (or `--set all`).
- **hard** (17 tasks, held out): written after core + extended were all passing on the owner's Mac (0.19.2, 110/110),
  so there is room left to measure. Multi-step reasoning, a question where the obvious answer is wrong, a bug fix,
  look-alike and twice-corrected memories, a busy week, acting on what a file says, contradictions and false
  premises. `jarvis bench run --set hard`. **Not** part of `--set all`, so earlier "all" runs stay comparable.
  Rule: JARVIS is never tuned to these tasks' wording; a fix has to be general, and it is checked on core + extended
  too. Two known gaps fail even with a perfect model (JARVIS never shows it the facts): `hard-planning-today`
  ("overdue or due today" lists only the overdue reminders) and `hard-memory-combine` (keyword recall misses the
  flight memory). `tests/test_bench_hard.py` checks that a perfect stand-in passes everything else and a
  plausible-but-wrong one fails all 17.

**Known gap, on purpose:** `memory-preferences` fails even with a perfect model, because memory recall is by
keywords ("suggest a dinner and greet me by name" never brings up "call me Ken" / "I'm vegetarian"). It's kept as a
target for the Outcome Engine (milestone M-C), so its fix can be measured.

## Run JARVIS on them (on the Mac)

```bash
uv run jarvis bench list
```
```bash
uv run jarvis bench run --run-code
```
Local models only (Claude off), all tasks except research. About 20–60 minutes on an Intel Mac. To include Claude
(your Pro plan: no money, but it uses your usage limits):
```bash
uv run jarvis bench run --models hybrid --run-code
```
Results go to `~/Library/Application Support/JARVIS/bench-results/<run>/` (`report.md`, `results.json`, and the
files each task produced).

**Isolation:** every task runs in a throwaway JARVIS data folder with made-up files, memories, calendar and
reminders, a stand-in for the Mac apps (nothing reaches your real Calendar, Reminders or Notes), and no standing
permissions: every change needs an approval, given or refused by the task's rules (`[approve] match`), and the
harness fails any task where something changed without one. Your real memory, history, approvals and privacy grants
are never read or changed. A run refuses to start unless your budget is $0. In `hybrid` runs the throwaway folder
may send its made-up data to Claude without asking; your real JARVIS still asks every time.

**`--run-code`:** coding answers are run against hidden test cases in a child process: isolated Python, empty
environment, 10 s limit, and on macOS inside `sandbox-exec` with no network and no writes outside a temp folder.
Without the flag, coding tasks are marked partial.

## The standalone baseline (from your phone)

```bash
uv run jarvis bench baseline           # B0: just the prompts ("as you'd really use it")
uv run jarvis bench baseline --b1      # B1: prompts + the same files/facts/calendar JARVIS starts with
```
Open the file it writes, do each task in a **new** chat in the Claude app (same model tier JARVIS uses for hard
work), paste the answer under the line, and note the time and what you had to do. Then:
```bash
uv run jarvis bench score-baseline "<path to the file>"
```
The same text checks score it. Checks that need files, approvals or Mac-app calls are marked "–" (not scored) for
the app, since it can't do those; your "effort" notes record what you did by hand instead.

## Adding a task

One file in `bench/tasks/<id>.toml`: `prompt`, `mode` (`chat`, `do`, `research`), optional `[setup]` (`files`,
`memories`, `forget`, `[setup.mac]` events/reminders/notes with day offsets), `[approve] match`, and `[[checks]]`
(see `src/jarvis/bench/scoring.py`). Each run records every task file's SHA-256, so results always say exactly which
version of a task they came from. Write the checks **before** running anything.

## What a result means (and doesn't)

12 tasks with one run each can only show large differences; use `--repeat 3` for anything you want to rely on. Pass
rates describe these tasks on this Mac at this date, not general intelligence.

## Before / after: the merge rule

```bash
uv run jarvis bench compare --before RUN_A RUN_B --after RUN_C RUN_D
```

Each side can pool several runs. A task passes when more than half of all its runs pass. A change may merge only if
at least 2 more tasks pass, no task that passed now fails, Claude calls rise by at most 25%, every change was
approved, **and every compared task has at least 5 runs on each side**. With fewer, the verdict is
**INCONCLUSIVE**: three runs let luck flip a task (on the owner's Mac one task went 2/3 → 0/3 with identical
answering code). Each changed task is marked *clear change* or *could be luck* (two-sided Fisher exact test,
p < 0.05). Exit codes: 0 merge, 3 don't merge, 4 inconclusive.

## Correcting a check: re-score, don't rerun

If a text check (contains, regex, number) turns out too strict or too loose, fix it in the task file, then:

```bash
uv run jarvis bench rescore RUN_DIR [RUN_DIR..]
uv run jarvis bench compare --rescored --before … --after …
```

`rescore` re-applies the corrected text checks to the saved answers and writes `results.rescored.json` beside the
original (never modified). Other checks keep their recorded results. It refuses a task whose prompt, setup or
non-text checks changed (old answers would be to a different question), or whose old version isn't in git history.
