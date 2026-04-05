import * as vscode from "vscode";
import { extractDeclaredName } from "./functionPatterns";
import type { CodebaseMap, ReadingOrderEntry } from "./types";

/** Maximum number of callers/callees to show before truncating. */
const MAX_DISPLAY_ITEMS = 5;

/** Entry from the MCP set_codelens tool. */
export interface McpCodeLensEntry {
  line: number;
  text: string;
  command?: string;
}

/**
 * Provides CodeLens annotations showing caller/callee information
 * above each exported function declaration.
 *
 * Data comes from map.json (via updateMapData). The MCP set_codelens
 * tool can override automatic annotations for specific files.
 */
export class CodeLensProvider implements vscode.CodeLensProvider {
  private mapData: CodebaseMap | undefined;
  private mcpOverrides = new Map<string, McpCodeLensEntry[]>();
  private changeEmitter = new vscode.EventEmitter<void>();

  /** Event that fires when CodeLens data changes. */
  readonly onDidChangeCodeLenses: vscode.Event<void> =
    this.changeEmitter.event;

  /**
   * Updates the stored map data and signals a CodeLens refresh.
   */
  updateMapData(map: CodebaseMap | undefined): void {
    this.mapData = map;
    this.changeEmitter.fire();
  }

  /**
   * Sets MCP-provided CodeLens overrides for a file.
   * When overrides are set, automatic caller/callee annotations
   * are replaced with the MCP entries.
   */
  setMcpOverrides(relativePath: string, entries: McpCodeLensEntry[]): void {
    this.mcpOverrides.set(relativePath, entries);
    this.changeEmitter.fire();
  }

  /**
   * Clears MCP overrides for a file, reverting to automatic annotations.
   */
  clearMcpOverrides(relativePath: string): void {
    this.mcpOverrides.delete(relativePath);
    this.changeEmitter.fire();
  }

  /**
   * Provides CodeLens items for the given document.
   */
  provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
    if (!this.mapData) {
      return [];
    }

    const relativePath = this.resolveRelativePath(document.uri.fsPath);
    if (!relativePath) {
      return [];
    }

    // If MCP overrides exist for this file, use those instead
    const overrides = this.mcpOverrides.get(relativePath);
    if (overrides) {
      return this.buildMcpCodeLenses(overrides);
    }

    const entry = this.findReadingOrderEntry(relativePath);
    if (!entry) {
      return [];
    }

    return this.buildAutoCodeLenses(document, entry);
  }

  /**
   * Disposes all resources.
   */
  dispose(): void {
    this.changeEmitter.dispose();
    this.mcpOverrides.clear();
  }

  /**
   * Builds CodeLens items from MCP-provided overrides.
   */
  private buildMcpCodeLenses(entries: McpCodeLensEntry[]): vscode.CodeLens[] {
    return entries.map((entry) => {
      const position = new vscode.Position(entry.line - 1, 0);
      const range = new vscode.Range(position, position);
      return new vscode.CodeLens(range, {
        title: entry.text,
        command: entry.command ?? "",
      });
    });
  }

  /**
   * Builds automatic caller/callee CodeLens items by scanning
   * the document for exported function declarations.
   */
  private buildAutoCodeLenses(
    document: vscode.TextDocument,
    entry: ReadingOrderEntry,
  ): vscode.CodeLens[] {
    const result: vscode.CodeLens[] = [];
    const exports = new Set(entry.exports);

    for (let lineIndex = 0; lineIndex < document.lineCount; lineIndex++) {
      const lineText = document.lineAt(lineIndex).text;
      const declaredName = extractDeclaredName(lineText);

      if (declaredName && exports.has(declaredName)) {
        const codeLens = this.createCallerCalleeCodeLens(
          lineIndex,
          entry,
        );
        result.push(codeLens);
      }
    }

    return result;
  }

  /**
   * Creates a single CodeLens with caller/callee text for a function.
   */
  private createCallerCalleeCodeLens(
    lineIndex: number,
    entry: ReadingOrderEntry,
  ): vscode.CodeLens {
    const position = new vscode.Position(lineIndex, 0);
    const range = new vscode.Range(position, position);

    const callersPart = formatCallersPart(entry.imported_by);
    const calleesPart = formatCalleesPart(entry.imports);

    const title = calleesPart
      ? `${callersPart} | ${calleesPart}`
      : callersPart;

    // First caller is the navigation target (if any exist)
    const firstCaller =
      entry.imported_by.length > 0 ? entry.imported_by[0] : undefined;
    const repoRoot = this.mapData?.repo_root ?? "";

    return new vscode.CodeLens(range, {
      title,
      command: "noLongerVibe.navigateToCaller",
      arguments: [
        firstCaller
          ? resolveAbsolutePath(repoRoot, firstCaller)
          : undefined,
      ],
    });
  }

  /**
   * Resolves an absolute file path to a path relative to repo_root.
   */
  private resolveRelativePath(absolutePath: string): string | undefined {
    if (!this.mapData) {
      return undefined;
    }

    const normalizedRoot = this.mapData.repo_root.endsWith("/")
      ? this.mapData.repo_root.slice(0, -1)
      : this.mapData.repo_root;

    if (!absolutePath.startsWith(normalizedRoot)) {
      return undefined;
    }

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
}

/**
 * Extracts the basename from a file path (e.g., "src/models/user.ts" -> "user.ts").
 */
function basename(filePath: string): string {
  const parts = filePath.split("/");
  return parts[parts.length - 1] ?? filePath;
}

/**
 * Formats the "Called by:" part of the CodeLens text.
 */
function formatCallersPart(importedBy: string[]): string {
  if (importedBy.length === 0) {
    return "Called by: none (potential dead code)";
  }

  const basenames = importedBy.map(basename);
  if (basenames.length <= MAX_DISPLAY_ITEMS) {
    return `Called by: ${basenames.join(", ")}`;
  }

  const shown = basenames.slice(0, MAX_DISPLAY_ITEMS);
  const remaining = basenames.length - MAX_DISPLAY_ITEMS;
  return `Called by: ${shown.join(", ")} ... +${String(remaining)} more`;
}

/**
 * Formats the "Calls:" part of the CodeLens text.
 * Returns empty string if there are no callees (caller omits the section).
 */
function formatCalleesPart(imports: string[]): string {
  if (imports.length === 0) {
    return "";
  }

  const basenames = imports.map(basename);
  if (basenames.length <= MAX_DISPLAY_ITEMS) {
    return `Calls: ${basenames.join(", ")}`;
  }

  const shown = basenames.slice(0, MAX_DISPLAY_ITEMS);
  const remaining = basenames.length - MAX_DISPLAY_ITEMS;
  return `Calls: ${shown.join(", ")} ... +${String(remaining)} more`;
}

/**
 * Resolves a relative path to absolute using the repo root.
 */
function resolveAbsolutePath(repoRoot: string, relativePath: string): string {
  const normalizedRoot = repoRoot.endsWith("/")
    ? repoRoot.slice(0, -1)
    : repoRoot;
  return `${normalizedRoot}/${relativePath}`;
}
