import * as vscode from "vscode";
import type { CodebaseMap, ReadingOrderEntry } from "./types";

/**
 * Color pair for light and dark themes.
 */
interface ThemeColorPair {
  light: string;
  dark: string;
}

/**
 * Caller count color tiers per the approved design spec.
 *
 * | Count | Light     | Dark      | Meaning        |
 * |-------|-----------|-----------|----------------|
 * | 0     | #dc2626   | #ef4444   | Dead code      |
 * | 1-2   | #94a3b8   | #64748b   | Low usage      |
 * | 3-7   | #475569   | #94a3b8   | Normal         |
 * | 8+    | #1e40af   | #60a5fa   | Hot path       |
 */
const CALLER_COLORS = {
  dead: { light: "#dc2626", dark: "#ef4444" },
  low: { light: "#94a3b8", dark: "#64748b" },
  normal: { light: "#475569", dark: "#94a3b8" },
  hot: { light: "#1e40af", dark: "#60a5fa" },
} as const;

/**
 * Regex patterns for detecting function/class declaration lines.
 * Each pattern is matched against individual lines of source code.
 */
const FUNCTION_PATTERNS: RegExp[] = [
  // JS/TS: function declarations (with optional export/async/default)
  /(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)/,
  // JS/TS: arrow function or function expression assignments
  /(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>/,
  // JS/TS: class declarations
  /(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)/,
  // Python: def statements
  /^(?:\s*)(?:async\s+)?def\s+(\w+)\s*\(/,
  // Python: class statements
  /^(?:\s*)class\s+(\w+)/,
];

/**
 * Provides caller count gutter decorations for function declarations.
 *
 * Shows a small count badge next to each function/class declaration
 * indicating how many files import the containing module. Uses the
 * `before` content decoration approach (text, not SVG) for simplicity.
 *
 * Colors are tiered by caller count:
 * - 0 callers: red (dead code)
 * - 1-2 callers: muted slate (low usage)
 * - 3-7 callers: default text weight (normal)
 * - 8+ callers: indigo accent (hot path)
 */
export class CallerCountProvider {
  private mapData: CodebaseMap | undefined;
  private decorationTypes: vscode.TextEditorDecorationType[] = [];
  private disposables: vscode.Disposable[] = [];

  /**
   * Returns the color pair for the given caller count.
   */
  static getCallerColor(count: number): ThemeColorPair {
    if (count === 0) {
      return CALLER_COLORS.dead;
    }
    if (count <= 2) {
      return CALLER_COLORS.low;
    }
    if (count <= 7) {
      return CALLER_COLORS.normal;
    }
    return CALLER_COLORS.hot;
  }

  /**
   * Updates the stored map data and refreshes decorations on the active editor.
   */
  updateMapData(map: CodebaseMap | undefined): void {
    this.mapData = map;
    const editor = vscode.window.activeTextEditor;
    if (editor) {
      this.updateDecorations(editor);
    }
  }

  /**
   * Computes and applies caller count decorations to the given editor.
   */
  updateDecorations(editor: vscode.TextEditor): void {
    // Dispose previous decoration types
    this.clearDecorations();

    if (!this.mapData) {
      return;
    }

    const filePath = editor.document.uri.fsPath;
    const relativePath = this.resolveRelativePath(filePath);

    if (!relativePath) {
      return;
    }

    const entry = this.findReadingOrderEntry(relativePath);
    if (!entry) {
      return;
    }

    const callerCount = entry.imported_by.length;
    const exports = new Set(entry.exports);
    const document = editor.document;

    // Scan each line for function/class declarations that match exports
    for (let lineIndex = 0; lineIndex < document.lineCount; lineIndex++) {
      const lineText = document.lineAt(lineIndex).text;
      const declaredName = this.extractDeclaredName(lineText);

      if (declaredName && exports.has(declaredName)) {
        this.applyDecoration(editor, lineIndex, callerCount);
      }
    }
  }

  /**
   * Disposes all resources held by this provider.
   */
  dispose(): void {
    this.clearDecorations();
    for (const d of this.disposables) {
      d.dispose();
    }
    this.disposables = [];
  }

  /**
   * Resolves an absolute file path to a path relative to repo_root.
   * Returns undefined if the file is not under repo_root.
   */
  private resolveRelativePath(absolutePath: string): string | undefined {
    if (!this.mapData) {
      return undefined;
    }

    const repoRoot = this.mapData.repo_root;
    // Normalize: ensure repo_root ends without trailing slash
    const normalizedRoot = repoRoot.endsWith("/")
      ? repoRoot.slice(0, -1)
      : repoRoot;

    if (!absolutePath.startsWith(normalizedRoot)) {
      return undefined;
    }

    // Strip repo_root prefix and leading slash
    const relative = absolutePath.slice(normalizedRoot.length);
    return relative.startsWith("/") ? relative.slice(1) : relative;
  }

  /**
   * Finds the ReadingOrderEntry for a given relative path.
   */
  private findReadingOrderEntry(
    relativePath: string,
  ): ReadingOrderEntry | undefined {
    return this.mapData?.reading_order.find(
      (entry) => entry.path === relativePath,
    );
  }

  /**
   * Extracts the declared name from a line of code, if it contains
   * a function, class, or method declaration.
   */
  private extractDeclaredName(lineText: string): string | undefined {
    for (const pattern of FUNCTION_PATTERNS) {
      const match = pattern.exec(lineText);
      if (match?.[1]) {
        return match[1];
      }
    }
    return undefined;
  }

  /**
   * Creates a decoration type and applies it to the given line.
   */
  private applyDecoration(
    editor: vscode.TextEditor,
    lineIndex: number,
    callerCount: number,
  ): void {
    const color = CallerCountProvider.getCallerColor(callerCount);
    const decorationType = vscode.window.createTextEditorDecorationType({
      before: {
        contentText: String(callerCount),
        color: color.light,
        margin: "0 8px 0 0",
        fontWeight: callerCount === 0 ? "bold" : "normal",
        fontStyle: "normal",
      },
      dark: {
        before: {
          contentText: String(callerCount),
          color: color.dark,
          margin: "0 8px 0 0",
          fontWeight: callerCount === 0 ? "bold" : "normal",
          fontStyle: "normal",
        },
      },
    });

    this.decorationTypes.push(decorationType);

    const range = new vscode.Range(
      new vscode.Position(lineIndex, 0),
      new vscode.Position(lineIndex, 0),
    );

    editor.setDecorations(decorationType, [{ range }]);
  }

  /**
   * Clears all active decoration types.
   */
  private clearDecorations(): void {
    for (const dt of this.decorationTypes) {
      dt.dispose();
    }
    this.decorationTypes = [];
  }
}
