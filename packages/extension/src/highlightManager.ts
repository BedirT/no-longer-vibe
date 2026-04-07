import * as vscode from "vscode";
import type { McpToolEvent, HighlightStyle } from "./mcpServer";

/** Decoration style configuration for each highlight type. */
interface DecorationStyleConfig {
  backgroundColor: string;
  borderLeft?: string;
}

/** Exact style specs from BED-83. */
const STYLE_CONFIGS: Record<HighlightStyle, DecorationStyleConfig> = {
  focus: {
    backgroundColor: "rgba(59, 130, 246, 0.07)",
    borderLeft: "3px solid rgba(59, 130, 246, 0.5)",
  },
  context: {
    backgroundColor: "rgba(148, 163, 184, 0.06)",
    // No border — secondary, should not compete for attention
  },
  warning: {
    backgroundColor: "rgba(245, 158, 11, 0.07)",
    borderLeft: "3px solid rgba(245, 158, 11, 0.5)",
  },
  "blast-radius": {
    backgroundColor: "rgba(239, 68, 68, 0.07)",
    borderLeft: "3px solid rgba(239, 68, 68, 0.4)",
  },
};

/** Importance tier names for focus-style highlights (BED-100). */
type ImportanceTier = "critical" | "important" | "standard" | "low";

/**
 * Opacity-tiered configs for importance-weighted focus highlights.
 * 8 decoration types total (4 base + 4 tiers), but a single file view
 * shows at most 3-4 simultaneous channels (context + 1-2 tiers),
 * staying within the SPEC's research-based limit.
 */
const IMPORTANCE_TIER_CONFIGS: Record<ImportanceTier, DecorationStyleConfig> = {
  critical: {
    backgroundColor: "rgba(59, 130, 246, 0.14)",
    borderLeft: "4px solid rgba(59, 130, 246, 0.7)",
  },
  important: {
    backgroundColor: "rgba(34, 197, 94, 0.10)",
    borderLeft: "3px solid rgba(34, 197, 94, 0.5)",
  },
  standard: {
    backgroundColor: "rgba(148, 163, 184, 0.08)",
    borderLeft: "2px solid rgba(148, 163, 184, 0.3)",
  },
  low: {
    backgroundColor: "rgba(148, 163, 184, 0.04)",
  },
};

/** Maps a 0.0-1.0 importance value to a tier name. */
function importanceToTier(importance: number): ImportanceTier {
  if (importance >= 0.75) return "critical";
  if (importance >= 0.5) return "important";
  if (importance >= 0.25) return "standard";
  return "low";
}

/** A tracked highlight applied to a file. */
export interface TrackedHighlight {
  style: HighlightStyle;
  startLine: number;
  endLine: number;
  importance?: number;
}

/**
 * Manages text editor decorations for highlight ranges.
 *
 * Creates decoration types for each highlight style on construction
 * and subscribes to MCP tool events for highlight_range, clear_highlights,
 * and clear_all commands.
 */
export class HighlightManager {
  /** Decoration types keyed by style name. */
  private readonly decorationTypes: Map<
    HighlightStyle,
    vscode.TextEditorDecorationType
  > = new Map();

  /** Importance-tiered decoration types for focus highlights (BED-100). */
  private readonly importanceTierTypes: Map<
    ImportanceTier,
    vscode.TextEditorDecorationType
  > = new Map();

  /** Active highlights per file path. */
  private readonly activeHighlights: Map<string, TrackedHighlight[]> =
    new Map();

  /** Event subscription disposable. */
  private readonly eventSubscription: vscode.Disposable;

  /** Editor change subscription for reapplying decorations on tab switch. */
  private readonly editorChangeSubscription: vscode.Disposable;

  /** Whether this manager has been disposed. */
  private disposed = false;

  constructor(onToolEvent: vscode.Event<McpToolEvent>) {
    // Create decoration types for all four base styles
    for (const [style, config] of Object.entries(STYLE_CONFIGS)) {
      const options: vscode.DecorationRenderOptions = {
        backgroundColor: config.backgroundColor,
        isWholeLine: true,
      };

      if (config.borderLeft) {
        options.borderLeft = config.borderLeft;
      }

      const decorationType =
        vscode.window.createTextEditorDecorationType(options);
      this.decorationTypes.set(style as HighlightStyle, decorationType);
    }

    // Create decoration types for importance tiers (BED-100)
    for (const [tier, config] of Object.entries(IMPORTANCE_TIER_CONFIGS)) {
      const options: vscode.DecorationRenderOptions = {
        backgroundColor: config.backgroundColor,
        isWholeLine: true,
      };

      if (config.borderLeft) {
        options.borderLeft = config.borderLeft;
      }

      const decorationType =
        vscode.window.createTextEditorDecorationType(options);
      this.importanceTierTypes.set(tier as ImportanceTier, decorationType);
    }

    // Subscribe to MCP tool events
    this.eventSubscription = onToolEvent((event) => {
      if (this.disposed) {
        return;
      }
      this.handleToolEvent(event);
    });

    // Reapply highlights when switching back to a file
    this.editorChangeSubscription = vscode.window.onDidChangeActiveTextEditor(
      (editor) => {
        if (this.disposed || !editor) {
          return;
        }
        // Check all tracked files for a match
        for (const filePath of this.activeHighlights.keys()) {
          const editorPath = editor.document.uri.fsPath;
          if (editorPath === filePath || editorPath.endsWith(`/${filePath}`)) {
            this.applyDecorationsForFile(filePath);
            break;
          }
        }
      },
    );
  }

  /**
   * Returns tracked highlights for a file, or undefined if none.
   */
  getHighlightsForFile(filePath: string): TrackedHighlight[] | undefined {
    const highlights = this.activeHighlights.get(filePath);
    if (!highlights || highlights.length === 0) {
      return undefined;
    }
    return highlights;
  }

  /**
   * Disposes all decoration types and clears state.
   */
  dispose(): void {
    this.disposed = true;
    this.eventSubscription.dispose();
    this.editorChangeSubscription.dispose();

    for (const decorationType of this.decorationTypes.values()) {
      decorationType.dispose();
    }
    for (const decorationType of this.importanceTierTypes.values()) {
      decorationType.dispose();
    }
    this.decorationTypes.clear();
    this.importanceTierTypes.clear();
    this.activeHighlights.clear();
  }

  /** Routes MCP tool events to handlers. */
  private handleToolEvent(event: McpToolEvent): void {
    switch (event.tool) {
      case "highlight_range":
        this.handleHighlightRange(event.params);
        break;
      case "clear_highlights":
        this.handleClearHighlights(event.params);
        break;
      case "clear_all":
        this.handleClearAll();
        break;
    }
  }

  /** Handles the highlight_range tool event. */
  private handleHighlightRange(params: Record<string, unknown>): void {
    const file = params.file as string;
    const startLine = params.startLine as number;
    const endLine = params.endLine as number;
    const style = params.style as HighlightStyle;
    const importance = params.importance as number | undefined;

    const highlight: TrackedHighlight = { style, startLine, endLine, importance };

    // Add to tracking
    const existing = this.activeHighlights.get(file) ?? [];
    existing.push(highlight);
    this.activeHighlights.set(file, existing);

    // Apply decorations to visible editors
    this.applyDecorationsForFile(file);
  }

  /** Clears highlights for a specific file. Public API for use by commands. */
  clearHighlightsForFile(filePath: string): void {
    this.activeHighlights.delete(filePath);
    this.clearDecorationsForFile(filePath);
  }

  /** Handles the clear_highlights tool event. */
  private handleClearHighlights(params: Record<string, unknown>): void {
    const file = params.file as string | undefined;

    if (file) {
      this.activeHighlights.delete(file);
      this.clearDecorationsForFile(file);
    } else {
      this.clearAllDecorations();
    }
  }

  /** Handles the clear_all tool event. */
  private handleClearAll(): void {
    this.clearAllDecorations();
  }

  /**
   * Applies all tracked decorations for a file to visible editors.
   */
  private applyDecorationsForFile(filePath: string): void {
    const highlights = this.activeHighlights.get(filePath);
    if (!highlights) {
      return;
    }

    // Find visible editors for this file
    const editors = this.findEditorsForFile(filePath);

    // Group highlights by style (base styles)
    const rangesByStyle = new Map<HighlightStyle, vscode.Range[]>();
    // Group importance-tiered highlights by tier
    const rangesByTier = new Map<ImportanceTier, vscode.Range[]>();

    for (const highlight of highlights) {
      const range = this.toRange(highlight.startLine, highlight.endLine);

      if (
        highlight.style === "focus" &&
        highlight.importance !== undefined
      ) {
        // Use importance-tiered decoration instead of base focus
        const tier = importanceToTier(highlight.importance);
        const ranges = rangesByTier.get(tier) ?? [];
        ranges.push(range);
        rangesByTier.set(tier, ranges);
      } else {
        // Use base style decoration
        const ranges = rangesByStyle.get(highlight.style) ?? [];
        ranges.push(range);
        rangesByStyle.set(highlight.style, ranges);
      }
    }

    // Apply decorations to each editor
    for (const editor of editors) {
      // Apply base style decorations
      for (const [style, decorationType] of this.decorationTypes) {
        const ranges = rangesByStyle.get(style) ?? [];
        editor.setDecorations(decorationType, ranges);
      }
      // Apply importance tier decorations
      for (const [tier, decorationType] of this.importanceTierTypes) {
        const ranges = rangesByTier.get(tier) ?? [];
        editor.setDecorations(decorationType, ranges);
      }
    }
  }

  /**
   * Clears all decorations for a specific file.
   */
  private clearDecorationsForFile(filePath: string): void {
    const editors = this.findEditorsForFile(filePath);

    for (const editor of editors) {
      for (const decorationType of this.decorationTypes.values()) {
        editor.setDecorations(decorationType, []);
      }
      for (const decorationType of this.importanceTierTypes.values()) {
        editor.setDecorations(decorationType, []);
      }
    }
  }

  /**
   * Clears all highlights and decorations across all files.
   */
  private clearAllDecorations(): void {
    const filePaths = Array.from(this.activeHighlights.keys());
    this.activeHighlights.clear();

    for (const filePath of filePaths) {
      this.clearDecorationsForFile(filePath);
    }
  }

  /**
   * Converts 1-indexed line numbers from MCP to 0-indexed VS Code Range.
   */
  private toRange(startLine: number, endLine: number): vscode.Range {
    return new vscode.Range(
      new vscode.Position(startLine - 1, 0),
      new vscode.Position(endLine - 1, 0),
    );
  }

  /**
   * Finds visible text editors that have the given file open.
   * Matches by file path suffix since MCP sends relative paths.
   */
  private findEditorsForFile(filePath: string): vscode.TextEditor[] {
    return vscode.window.visibleTextEditors.filter((editor) => {
      const editorPath = editor.document.uri.fsPath;
      return editorPath === filePath || editorPath.endsWith(`/${filePath}`);
    });
  }
}
