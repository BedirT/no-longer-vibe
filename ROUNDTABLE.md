# Roundtable Discussion Log

Record of the ideation process that produced SPEC.md.

## Panel

| Name | Role | Key Contribution |
|------|------|-----------------|
| Maya Chen | Product Strategist (ex-Stripe, Vercel) | Stripped to bones: 3 commands, 1 JSON, build in an afternoon |
| Dr. Lena Park | DX Researcher (CMU PhD, ex-MSR) | Research-backed reading order, validated 100% coverage for architect-verifying-implementation, killed batch annotations with ICAP framework |
| James Okafor | Systems Architect (ex-JetBrains, GitHub) | Technical architecture, parser feasibility, VS Code MCP assessment, hybrid recommendation |
| Raf Dominguez | The Skeptic (senior engineer) | Stress-tested every assumption, defined the exit condition question, accepted the framing after challenge |
| Sam Torres | Vibe-Coder Practitioner (indie hacker) | Real pain points, UX preferences, "reading is pull not push", killed VS Code puppeteering |

## Key Decisions (3 rounds)

### Round 1: Initial Analysis
- Problem is real but reframed: not "I haven't read the code" but "I can't navigate and change confidently"
- 100% coverage initially challenged by 4/5 panelists
- Sam reframed as "search tool not reading tool" (later reversed)
- Annotations debated: risk of hall-of-mirrors (Raf), annotation substitution (Park)
- VS Code extension identified as most integrated but most complex

### Round 2: Creator Clarifies Intent
- NOT a product. Personal tool.
- Creator WANTS to read everything. 2x investment model.
- Must be Claude Code compatible. No extra cost.
- Panel converges: parser + Claude Code skill + JSON state
- Dr. Park reverses on 100%: "For architect verifying implementation, full coverage is necessary"
- Sam reverses: "They designed the architecture. That's ownership, not curiosity."
- Raf drops 60% of objections. Leaves one hard question: define the exit condition.
- Creator answers: three-tier (confirmed / flagged / skimmed)

### Round 3: Annotation Architecture
- Creator asks: batch annotations vs live conversation vs hybrid?
- Unanimous: Hybrid (structural pre-computed, semantic live)
- Batch killed: expensive, stale, creates passive learning
- VS Code MCP control killed: ecosystem immature, "reading is pull not push"
- Context window solution: accumulated summaries in progress.json

### Round 4: VS Code Extension UX
- Creator wants reading to feel "alive," not dry terminal + editor
- Sam updates: decoration ≠ puppeteering. "If it changes how what I'm looking at appears, it's decoration. One steals agency, the other augments it."
- James: full technical architecture. Extension = display driver (reads map.json), Claude = director (MCP commands). Tiered build plan.
- Sam's "never going back" moment: caller count in gutter. Dead code detection at a glance.
- Dr. Park: max 3-4 visual channels (Yeh & Wickens, 2001). Deviation highlighting > complexity gradients. Single binary gutter signal > graduated warnings.
- Panel kills: animated decorations, AI narration, importance heatmaps, AI-written code markers
- Blast radius visualization identified as the showstopper Tier 2 feature

## Research References (from Dr. Park)
- Letovsky (1987): Program understanding model (knowledge base + mental model + assimilation)
- Brooks (1983): Top-down comprehension through successive mapping reconstruction
- Soloway & Ehrlich (1984): Expert programmers recognize plans, chunk code
- Storey, Fracchia & Muller (1999): High-level structural overviews reduce comprehension time
- Ko, DeLine & Venolia (2007): Developers forage selectively for task-relevant information
- Pirolli & Card (1999): Information foraging theory — developers follow "information scent"
- Singer et al. (1997): Maintainers need deep understanding of 10-20%, familiarity with 30-40%
- Sweller (1988): Cognitive load theory — germane vs extraneous load
- Sridhara et al. (2010, 2011): Code summaries most effective for navigation/triage, not deep comprehension
- Chi (2014): ICAP framework — interactive > constructive > active > passive learning
- Kalyuga (2007): Redundancy effect — expert learners harmed by redundant explanations
- Bjork & Bjork (2011): Desirable difficulties — spaced retrieval consolidates comprehension
- Parnin & Rugaber (2012): Annotation during reading improves retention
- Ghosh & Gilboa (2014): Schema-congruent processing for experts
- Ausubel (1960): Advance organizers improve comprehension of unfamiliar material
- Busjahn et al. (2015): Eye-tracking shows developers scan for structural anchors, not linear reading
- Sharafi et al. (2015): Visual attention patterns in code reading
- Hannebauer et al. (2018): Syntax highlighting has modest positive effects on comprehension speed
- Wickens et al. (2004): Applied attention theory — anomaly signaling effective when baseline is well-defined
- Yeh & Wickens (2001): Clutter blindness threshold at 4-7 simultaneous visual channels in HUD research
- Miara et al. (1983): Visual block structure (indentation guides) aids nesting depth comprehension
