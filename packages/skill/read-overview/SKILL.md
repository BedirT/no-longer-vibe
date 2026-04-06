---
name: read-overview
description: Show a high-level orientation of the project before diving into file-by-file reading
triggers:
  - /read-overview
---

# /read-overview

Produce a visual, engaging orientation for the codebase so the reader
has a mental map before starting `/read-next`. The overview is an HTML
page with charts and structure -- not terminal text. The reader should
finish it in under 90 seconds feeling "I understand the shape of this,
I'm ready to start reading."

## Prerequisites

- `.codebase-guide/map.json` must exist (run `/read-index` first).
- If `map.json` is missing, prompt the user to run `/read-index` and stop.

## Architecture: Investigate, Then Render

This skill uses a three-phase approach:

### Phase 1: Gather Information (Parallel Subagents)

Read `.codebase-guide/map.json` yourself first. Extract:
- `total_files`, layer names and file counts, `reading_order` entries
- Backbone files: the top 5-8 entries sorted by `imported_by` list
  length (these are the most-depended-on files in the codebase)
- Pass distribution: count entries whose `reason` starts with
  "Contract surface", "Data flow path", or "Utility code"
- Total line count: sum `line_count` across all reading_order entries

Then spawn **three subagents in parallel** using the Agent tool:

#### Subagent 1: `project-identity` (type: Explore)

Prompt the agent to:
- Find and read the project manifest file (`package.json`,
  `pyproject.toml`, `go.mod`, `Cargo.toml`, `requirements.txt`,
  `Gemfile`, or equivalent) in the repo root
- Read the first 40 lines of `README.md` if it exists
- List top-level directories

Ask it to return a structured summary:
- Project name
- Primary language(s)
- Package manager
- Framework(s) (e.g., Next.js, Flask, Gin)
- Top 5-10 runtime dependencies (not dev/test deps) -- the ones
  that define what the project *does*
- One-liner project description (from README or inferred)

#### Subagent 2: `structure-explorer` (type: Explore)

Give the agent the file path list from map.json. Prompt it to:
- Group files by directory prefix to identify **vertical feature
  areas** -- clusters of files that represent a single domain or
  subsystem (e.g., "auth", "billing", "notifications")
- For each feature area, note which layers it spans and list its
  key files (2-3 most central)
- Read the top 3 most-imported files (from the backbone list you
  extracted) -- just the first 30-40 lines each -- to understand
  what they export and represent

Ask it to return:
- A list of feature areas with names, layer spans, and key files
- A one-line characterization of each backbone file it read

#### Subagent 3: `reading-planner` (type: Plan)

Give the agent the reading order summary you extracted from map.json:
file count per pass, complexity distribution, total line count,
layer sizes. Prompt it to:
- Estimate total reading sessions (use ~35 files/session baseline)
- Break down effort by pass (contracts, data flow, utility)
- Identify the first 3-5 files in reading order with a short
  note on why each is first
- Note any heads-up about the reading journey (e.g., "the features
  layer is 49% of all files -- expect the middle sessions to be
  the longest stretch")
- Suggest 2-3 comprehension milestones at key pass boundaries
  (e.g., "After session 5: all type definitions understood")

Ask it to return a structured reading plan.

### Phase 2: Generate HTML Overview

Using map.json data and all three subagent results, generate a
self-contained HTML file at `.codebase-guide/overview.html`.

Use the template at `packages/skill/read-overview/overview-template.html`
as a reference for structure, CSS, and layout. The template contains
CSS custom properties, a 3-zone layout, and commented examples of
every element type. Generate the full HTML by populating it with
real data from your investigation.

**Key constraints:**
- Single self-contained file: all CSS and JS inline, no external
  dependencies (no CDN links). Must work offline, in VS Code preview.
- All charts are inline SVG or CSS -- no charting libraries.
- Dark mode support via `@media (prefers-color-scheme: dark)`.
- Total JS budget: under 80 lines (tooltips + click-to-copy).

**The three visual zones:**

#### Zone 1: Identity (header)

Light background. Project name (32px bold), one-liner description,
stat badges (file count, line count, language, framework, package
manager). Feels like a letterhead. ~160px tall.

#### Zone 2: The Map (main section, largest)

**Layer composition bar**: A single horizontal bar, full width,
44px tall. Five colored segments proportional to file count per
layer. Each segment shows its label if wide enough, otherwise
label goes below. Hover shows tooltip with description. Colors:
foundation=#4CA1A3, core=#6B7B8D, features=#D4A057,
integration=#C07070, entry=#8E99A4.

**Layer detail table**: Below the bar. Columns: colored dot + name,
file count, description. No visible borders, just bottom lines.

**Feature area cards** (left column): Each card has the area name,
file count, which layers it spans (as small colored dots), and
2-3 key file paths. Left border colored by dominant layer. If no
clear feature areas found, skip this section.

**Backbone files** (right column): Horizontal bar chart. Each file
has its name (monospace, click-to-copy), a proportional bar (fill
color matches its layer), and a dependency count. Below the bar,
a one-line characterization. Bars are proportional to the maximum
dependent count.

#### Zone 3: Your Path (bottom section)

**Reading journey track**: Full-width horizontal bar, 48px tall,
three colored segments for the three passes (contracts=#5B8FBF,
data_flow=#D4A057, utility=#7BA37B). Each segment sized by file
count proportion. Labels inside segments or below if too narrow.

**Comprehension milestones**: Below the journey track. 2-3
milestone markers with dashed top borders: "After session N:
<what you will have understood>." These transform the timeline
into a plan.

**First files list**: The first 3-5 files in reading order with
a numbered list, file path (monospace, click-to-copy), and reason.

**Heads-up box**: Optional. Notable things about the reading
journey. Light card with border.

**CTA**: Dark background card with monospace text:
"$ /read-next to begin reading"

If any subagent fails or returns incomplete data, generate the
HTML from whatever is available. Map.json alone is sufficient for
a useful (if less rich) overview.

### Phase 3: Terminal Output

After writing the HTML file, print a brief summary to the terminal:

```
Codebase overview generated.

  <total_files> files | <total_lines> lines | <language>
  <estimated_sessions> sessions estimated

  Open: .codebase-guide/overview.html

Run /read-next to begin reading.
```

Then attempt to open the file:
- If `open` command is available (macOS): run `open .codebase-guide/overview.html`
- Otherwise, just print the path for the user to open manually.

## Tone

- Orientation, not audit. Do not flag problems, dead code, or
  code quality issues. The reader will discover those during
  `/read-next`. The overview's job is to ground, not alarm.
- Concise, not exhaustive. Every element must earn its screen space.
- The HTML should feel like a well-designed dashboard -- clean,
  airy, professional. Think Stripe documentation aesthetic.

## VS Code Extension Integration (MCP Tools)

When MCP tools are available, call `update_progress_tree()` after
generating the overview so the sidebar reflects the current state.

## Edge Cases

- If `progress.json` exists and shows prior progress, add a
  "Resuming" banner at the top of the HTML: "<n>/<total> files
  read (<percent>%). Next file: <path>."
- Can be re-run anytime -- it regenerates from current state.
- If the codebase has fewer than 20 files, simplify the layout --
  skip feature areas and journey track, just show identity + layers
  + first files.
