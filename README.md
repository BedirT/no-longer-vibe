<p align="center">
  <img src="docs/assets/nlv-logo.png" alt="No Longer Vibe" width="120" />
</p>

<h1 align="center">No Longer Vibe</h1>

<p align="center"><em>Read your vibe-coded codebase, on purpose, with AI riding shotgun.</em></p>

<p align="center">
  <a href="#why-this-exists">Why</a> ·
  <a href="#getting-started">Getting Started</a> ·
  <a href="#a-typical-reading-session">Reading Session</a> ·
  <a href="#vs-code-extension">VS Code Extension</a>
</p>

---

## Why this exists

With the surge of AI agents and the rise of vibe coding, I myself got pretty deep into it. Weekend projects, things no one else would ever need, rewrites of stuff I just didn't want to pay for because I figured "I bet I could build this in a day with AI." I do, and I also use AI heavily as a co-author in my day job and personal work. One thing kept bugging me though: the vanishing of ownership.

Vibe coding comes with a debt. Do I even own this code anymore? Do I actually know what's happening in it? When I fire off three parallel agents on three Linear issues and the PRs come rolling in, I sometimes don't really want to read them line by line; I just want to get to the finished product. If you've ever been lazy like that, you've probably also had the moment where you wished you'd just sat down and read everything, so the project felt *owned* instead of *vibed*.

So I built this little tool for myself, and for anyone else who feels the same itch. It helps you read your codebase faster, with AI on the side to explain context as you go, and tracks your progress so you can actually finish.

It works well for me. If you want it too, help yourself.

---

## What it actually is

Three pieces, no infrastructure, no LLM in the analysis pipeline:

- **`nlv` CLI.** A deterministic Python parser. It walks your project, parses ASTs, builds a dependency graph, and writes a reading plan to `.codebase-guide/map.json`. Same repo in, same plan out.
- **Claude Code skill.** Sequences files for you, tracks progress, briefs Claude on each file before you read it so you can ask questions in context.
- **VS Code extension** (optional). Adds visual context to whatever file you're looking at: caller counts, blast radius, file-tree colors that match your reading progress.

<img width="700" alt="image" src="https://github.com/user-attachments/assets/76ce1663-d5fa-4d20-babc-3bb37d5ad287" />

---

## Getting started

You need Python 3.11+ with [uv](https://docs.astral.sh/uv/) and the [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI.

```bash
git clone https://github.com/BedirT/no-longer-vibe.git
cd no-longer-vibe
./install.sh
```

That installs the `nlv` CLI, the Claude Code skill, and the VS Code extension if VS Code is around. You can scope it with `--parser-only`, `--skill-only`, or `--extension-only` if you only want one piece.

Then point it at the project you want to read:

```bash
nlv /path/to/your/project
```

This is the only step that touches your filesystem. It writes `.codebase-guide/` into the project root with the parsed map and an empty progress file. No network calls, no LLM, no surprises.

---

## A typical reading session

Open your project in Claude Code (and VS Code on the side, if you installed the extension). From here on it's a loop.

**1. Ask for the next file.**

```
/read-next
```

Claude pulls the next file in reading order and gives you a short briefing: the layer it sits in, what it exports, what depends on it, which of its dependencies you've already read, and why this file came up now. Then it loads the file content into the conversation.

**2. Read it.**

Just read. The briefing tells you what to expect, so you're not flying blind. If you're using the extension, your file tree shows the file as currently-reading and you've got caller counts in the gutter as you scroll.

**3. Ask questions when something is weird.**

This is the part that makes the whole thing work. Claude already has context on the file and everything you've read before it, so you can just ask:

> *Why is there a dual token store in lines 47 to 52?*

And get a real answer that references the config you read earlier, instead of a generic explanation.

**4. Mark it and move on.**

When you're done with the file, tell Claude how it went:

- `done` (or `confirmed`) if you understood it and it matches what you'd have built yourself.
- `flag <reason>` if something surprised you and you want to come back to it later. The reason gets stored with the flag.
- `skim` if you read it but want a deeper pass another time.

Then `next`, and you're back at step 1.

**5. When you stop, just stop.**

Progress lives in `.codebase-guide/progress.json`. Close the laptop, come back tomorrow, run `/read-next` again. Claude gets fed compressed summaries of what you've already read so it stays oriented even though the previous conversation is gone. You don't have to re-explain anything.

**6. Revisit your flags.**

```
/read-flagged
```

Walks you through everything you flagged, with your original notes attached. This is usually where the real work happens, since flagged files are by definition the ones that surprised you.

---

## Why the order makes sense

`nlv` doesn't hand you files alphabetically. They're sorted into three passes, and within each pass everything is topologically sorted so you never read a file before its dependencies. Test files appear right after the implementation they cover.

1. **Contracts.** Types, interfaces, public APIs, module boundaries. You're pattern-matching against your own design intent. Goes fast.
2. **Data flow.** Primary execution paths end-to-end. This is where you spot where the AI's approach drifted from yours.
3. **Utility.** Helpers, error handling, fallbacks. Where AI made the most autonomous calls and where the weird stuff usually hides.

The reading order is also stratified by architectural layer. Every file gets classified into one of five layers based on where it sits in the dependency graph, and you read from the bottom up:

<img width="700" alt="image" src="https://github.com/user-attachments/assets/83478e6e-6180-4fae-a68e-0d891bbda0a3" />


Arrows point in the direction of dependency, so `foundation` is what everything else rests on, and `entry` is the last thing you read. The progress sidebar in the extension also groups files by layer, so you can see at a glance which floor of the building you're on.

---

## VS Code Extension

The extension adds visual context to whatever file you're looking at. Claude Code drives it over MCP, so Claude is the director and the extension is the display.

The principle is **decoration, not puppeteering**. It adds information to what you're already looking at. It does not move your cursor, switch your tabs, or otherwise demand attention.

> **Screenshot: extension overview.**
> *Wide shot of VS Code with the file tree on the left showing colored status dots, an open file with caller-count numbers in the gutter and CodeLens annotations above functions, and the progress sidebar visible on the right.*

**Caller count gutter.** A small number next to each function showing how many places call it. The single highest-value feature in the extension. Glance at a function, see `0`, realize the AI generated dead code, move on. No grep required.

> **Screenshot: caller count gutter.**
> *Close-up of a few function definitions with the call-count number rendered in the gutter beside each one. Include at least one zero-callers case.*

**File status decorations.** The file tree colors each file by its reading status:

- 🟢 confirmed
- 🟠 flagged
- 🔵 currently reading
- (no color) unread

> **Screenshot: file status in explorer.**
> *Narrow shot of the VS Code file explorer with a mix of green, orange, blue, and uncolored files visible in a folder.*

**Blast radius.** Pick a function, see every file that would be affected if you changed it. The transitive dependents tint orange in the explorer and Claude can walk you through the impact chain. Useful right before you touch anything load-bearing.

> **Screenshot: blast radius.**
> *File explorer with one selected function and around ten transitively dependent files tinted orange. A small overlay or sidebar showing the impact chain would be ideal.*

**CodeLens annotations.** Clickable "Called by" and "Calls" lines above each function so you can jump around without leaving the file.

**Progress sidebar.** Tree view organized by architectural layer, showing per-layer completion percentages. Always know where you are and how much is left.

---

## Commands

| Command | What it does |
|---|---|
| `nlv [path]` | Parse a codebase and write `.codebase-guide/map.json` |
| `/read-index [path]` | Same thing, from inside Claude Code |
| `/read-overview` | High-level orientation before diving in |
| `/read-next` | Next file in reading order, with structural briefing |
| `/read-status` | How far you are, by file and by layer |
| `/read-flagged` | Second pass through everything you flagged |
| `/read-refresh` | Re-parse, keep progress on unchanged files, invalidate stale ones |

---

## Languages

| Language | Parser | Imports |
|---|---|---|
| Python | built-in `ast` | relative and absolute |
| TypeScript / JavaScript | tree-sitter | module paths with index resolution |
| Go | tree-sitter | package-based |

The parser uses a plugin architecture. Each language implements `parse_file()` and `resolve_import()`, and adding a new one is a single file in `packages/parser/src/nlv/plugins/`. PRs welcome.

---

## Configuration

Drop a `config.toml` (or `.json`) in `.codebase-guide/` if you want to tweak things:

```toml
skip_tests = false
test_pass = "utility"           # contracts | data_flow | utility | separate | skip
tie_breaking = "alphabetical"   # alphabetical | file_size | complexity

[custom_pass_overrides]
"src/types/**" = "contracts"
"src/generated/**" = "utility"

[exclude_from_reading]
patterns = ["**/*.generated.ts", "**/migrations/**"]
```

<details>
<summary>All options</summary>

| Option | Default | What it does |
|---|---|---|
| `skip_tests` | `false` | Exclude test files entirely |
| `test_pass` | `"utility"` | Which pass unpaired tests land in |
| `tie_breaking` | `"alphabetical"` | Tiebreaker for the topological sort |
| `integration_fan_in_threshold` | `3` | Minimum fan-in to count as integration layer |
| `custom_pass_overrides` | `{}` | Force globs into specific passes |
| `exclude_from_reading` | `{}` | Globs to skip |
| `layer_thresholds` | (built-in) | Override layer depth boundaries |

**Test handling modes:**

- `utility`: unpaired tests land in pass 3, paired tests follow their implementation file. (Default.)
- `contracts` or `data_flow`: unpaired tests go in the named pass instead.
- `separate`: all tests go in a fourth pass after everything else.
- `skip`: exclude tests entirely.

</details>

---

## Incremental refresh

Codebases change while you're reading them. `/read-refresh` re-parses and tells you what happened:

```
Refreshed: /path/to/project
  Unchanged: 380 files (progress preserved)
  Modified:  3 files (reset to unread)
  New:       2 files (added as unread)
  Deleted:   1 file (removed)
  Stale:     7 files (dependency changed upstream)
```

When a file changes, its reverse dependencies get marked "potentially stale" even if their own content didn't change. The graph handles this for you, so you don't end up with a confidently-confirmed file whose foundations shifted under it.

---

## Project structure

```
packages/
  parser/             # Python CLI, the deterministic engine
    src/nlv/
      cli.py            # nlv entry point
      plugins/          # language plugins
      graph/            # dependency graph + cycle detection
      layers.py         # layer classifier
      reading_order.py  # three-pass ordering
      refresh.py        # incremental refresh + invalidation
  skill/              # Claude Code skill definitions
  extension/          # VS Code extension (TypeScript)
    src/
      extension.ts        # activation
      mcpServer.ts        # MCP stdio server
      callerCount.ts      # gutter decorations
      codeLensProvider.ts # caller/callee CodeLens
      blastRadius.ts      # blast radius viz
      progressTree.ts     # sidebar tree
```

---

## Development

```bash
# Parser
uv sync && uv run pytest -x
uv run ruff check .
uv run pyright

# Extension
cd packages/extension
npm install && npm run build
npm test
```

---

## Why it's built this way

A few opinions baked into the design, in case you're wondering:

- **Deterministic parser, no LLM in the analysis.** Same repo in, same map out. The LLM lives in the conversation, not in the pipeline.
- **Live context, not batch summaries.** Pre-generated AI annotations create passive learning. You skim, you nod, you don't actually engage. Asking Claude in the moment is the whole point.
- **Decoration, not puppeteering.** The extension augments what you're looking at and stays out of your way. No cursor jumps, no tab switches, no animated nonsense.
- **A measurable exit condition.** Progress tracking means you actually know when you're done. "All files confirmed" beats "I read most of it I think."
- **No "AI wrote this" markers.** Once you've read and confirmed a file, it's yours. There's no lingering second-class citizenship for vibe-coded code.

---

## License

[AGPL-3.0](LICENSE). Built for me first. If it's useful to you, help yourself.
