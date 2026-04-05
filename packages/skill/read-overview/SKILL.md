---
name: read-overview
description: Show a high-level orientation of the project before diving into file-by-file reading
triggers:
  - /read-overview
---

# /read-overview

Produce a concise, engaging orientation for the codebase so the reader
has a mental map before starting `/read-next`. The overview should feel
like walking into a building and looking around the lobby -- grounding,
not exhaustive. The reader should finish in under 90 seconds feeling
"I understand the shape of this, I'm ready to start reading."

## Prerequisites

- `.codebase-guide/map.json` must exist (run `/read-index` first).
- If `map.json` is missing, prompt the user to run `/read-index` and stop.

## Architecture: Investigate, Then Narrate

This skill uses a two-phase approach:

### Phase 1: Gather Information (Parallel Subagents)

Read `.codebase-guide/map.json` yourself first. Extract:
- `total_files`, layer names and file counts, `reading_order` entries
- Backbone files: the top 5-8 entries sorted by `imported_by` list
  length (these are the most-depended-on files in the codebase)
- Pass distribution: count entries whose `reason` starts with
  "Contract surface", "Data flow path", or "Utility code"

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

Ask it to return a structured reading plan.

### Phase 2: Compose the Overview (You)

Using map.json data and all three subagent results, write a single
coherent overview in three acts. You are the sole narrator -- do not
paste subagent output directly. Synthesize it into a narrative.

If any subagent fails or returns incomplete data, compose the
overview from whatever is available. Map.json alone is sufficient
for a useful (if less rich) overview.

## Output Format: Three Acts

Keep the total output to **2 screens or less**. Aggressive formatting:
short lines, clear visual grouping, no paragraphs. This is orientation,
not documentation.

### Act 1: Identity

What is this project? One tight block.

```
-- Codebase Overview -----------------------------------------------

<Project name> -- <one-liner description>
<Language(s)> | <framework(s)> | <total files> files | ~<total lines>k lines
<Package manager> | <key deps summarized concisely>
```

This should feel like a book's back cover -- what kind of thing am I
about to read? Include scale (file count, line count) so the reader
has a sense of magnitude.

### Act 2: The Map

Two dimensions: horizontal layers and vertical feature areas.

```
Layers
  foundation    <n> files -- <description or representative examples>
  core          <n> files -- <description>
  features      <n> files -- <description>
  integration   <n> files -- <description>
  entry         <n> files -- <description>

Feature Areas
  <area>    <n> files across <layers> -- <key files>
  <area>    <n> files across <layers> -- <key files>
  ...

Backbone (everything connects through these)
  <path> ............. <n> dependents  (<brief characterization>)
  <path> ............. <n> dependents  (<brief characterization>)
  ...
```

The backbone files are the load-bearing walls. The reader will
encounter them early (they sit in foundation/core layers). Present
them as "these are the files the rest of the codebase is built on."

Feature areas show the vertical slices -- what the app *does*, not
just how the code is *structured*. If the structure-explorer could
not identify clear feature areas, skip this subsection.

### Act 3: Your Path

What the reading journey looks like, concretely.

```
Reading Plan
  Pass 1 (contracts):  <n> files -- types, interfaces, public APIs
  Pass 2 (data flow):  <n> files -- execution paths end-to-end
  Pass 3 (utility):    <n> files -- helpers, error handling, edge cases

  Estimated sessions: ~<n> at 35 files/session

First files
  1. <path> -- <why this is first, from reading_order reason>
  2. <path> -- <brief note>
  3. <path> -- <brief note>

<Any heads-up about the reading journey from the planner>
```

End with:
```
Run /read-next to begin reading.
```

## Tone

- Orientation, not audit. Do not flag problems, dead code, or
  code quality issues. The reader will discover those during
  `/read-next`. The overview's job is to ground, not alarm.
- Concise, not exhaustive. Every line must earn its screen space.
  If the reader could derive it from running `tree` or `ls`, cut it.
- One voice. The subagents gather data; you tell the story. The
  output should read as a single coherent narrative, not stitched
  sections from different sources.

## VS Code Extension Integration (MCP Tools)

When MCP tools are available, call `update_progress_tree()` after
displaying the overview so the sidebar reflects the current state.

No file opening or highlighting -- this is a summary view.

## Edge Cases

- If `progress.json` exists and shows prior progress, mention it
  briefly at the top of Act 3: "Resuming: <n>/<total> files read
  (<percent>%). Next file: <path>."
- Can be re-run anytime -- it always shows current state.
- If the codebase has fewer than 20 files, condense to a shorter
  format -- a full 3-act overview for a tiny project is overkill.
