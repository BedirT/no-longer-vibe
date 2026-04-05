import * as vscode from "vscode";
import type { CodebaseMap } from "./types";
import type { McpToolEvent } from "./mcpServer";

/** Result returned when blast radius is computed for a symbol. */
export interface BlastRadiusResult {
  /** The symbol that was looked up. */
  symbol: string;
  /** The file that exports the symbol. */
  sourceFile: string;
  /** All transitively affected file paths (excluding the source). */
  affectedFiles: string[];
  /** Count of affected files. */
  affectedCount: number;
}

/**
 * Provides blast radius visualization for the VS Code explorer.
 *
 * When `show_blast_radius(symbol)` is triggered via MCP:
 * 1. Finds the file exporting the symbol from map.json reading_order exports
 * 2. Walks reverse dependency edges (imported_by) transitively via BFS
 * 3. Applies orange tint to affected files in the explorer
 * 4. Returns the list of affected files and count to the caller
 *
 * Implements FileDecorationProvider so it can overlay decorations
 * on the explorer when blast radius is active.
 */
export class BlastRadiusProvider implements vscode.FileDecorationProvider {
  private readonly _onDidChangeFileDecorations =
    new vscode.EventEmitter<vscode.Uri | undefined>();
  readonly onDidChangeFileDecorations = this._onDidChangeFileDecorations.event;

  private mapData: CodebaseMap | undefined;
  private readonly workspaceRoot: string;

  /** Set of file paths currently in the active blast radius. */
  private affectedFilesSet = new Set<string>();

  /** The source file of the active blast radius, if any. */
  private sourceFile: string | undefined;

  constructor(workspaceRoot: string) {
    this.workspaceRoot = workspaceRoot;
  }

  /**
   * Updates the stored map data. Clears any active blast radius since
   * the dependency graph may have changed.
   */
  updateMapData(map: CodebaseMap | undefined): void {
    this.mapData = map;
    this.clearBlastRadius();
  }

  /**
   * Finds the file that exports the given symbol by scanning
   * reading_order entries.
   *
   * Returns the relative file path, or undefined if not found.
   */
  findFileForSymbol(symbol: string): string | undefined {
    if (!this.mapData) {
      return undefined;
    }

    for (const entry of this.mapData.reading_order) {
      if (entry.exports.includes(symbol)) {
        return entry.path;
      }
    }

    return undefined;
  }

  /**
   * Computes the transitive blast radius for a file by walking
   * reverse dependency edges (imported_by) via BFS.
   *
   * Returns all transitively affected file paths, excluding the
   * source file itself. Handles circular dependencies safely
   * via a visited set.
   */
  computeBlastRadius(filePath: string): string[] {
    if (!this.mapData) {
      return [];
    }

    const graph = this.mapData.dependency_graph;
    const visited = new Set<string>();
    const queue: string[] = [];

    // Seed the BFS with direct dependents
    const entry = graph[filePath];
    if (!entry) {
      return [];
    }

    for (const dep of entry.imported_by) {
      if (!visited.has(dep)) {
        visited.add(dep);
        queue.push(dep);
      }
    }

    // BFS: walk reverse edges transitively
    while (queue.length > 0) {
      const current = queue.shift()!;
      const currentEntry = graph[current];
      if (!currentEntry) {
        continue;
      }

      for (const dep of currentEntry.imported_by) {
        if (!visited.has(dep)) {
          visited.add(dep);
          queue.push(dep);
        }
      }
    }

    return Array.from(visited);
  }

  /**
   * Shows the blast radius for a symbol. Finds the file, computes
   * transitive dependents, and activates the visualization.
   *
   * Returns the blast radius result, or undefined if the symbol
   * was not found.
   */
  showBlastRadius(symbol: string): BlastRadiusResult | undefined {
    const filePath = this.findFileForSymbol(symbol);
    if (!filePath) {
      return undefined;
    }

    const affectedFiles = this.computeBlastRadius(filePath);

    this.sourceFile = filePath;
    this.affectedFilesSet = new Set(affectedFiles);

    // Fire global decoration change to refresh all file decorations
    this._onDidChangeFileDecorations.fire(undefined);

    return {
      symbol,
      sourceFile: filePath,
      affectedFiles,
      affectedCount: affectedFiles.length,
    };
  }

  /**
   * Clears the active blast radius visualization.
   */
  clearBlastRadius(): void {
    const wasActive = this.affectedFilesSet.size > 0 || this.sourceFile !== undefined;
    this.affectedFilesSet.clear();
    this.sourceFile = undefined;

    if (wasActive) {
      this._onDidChangeFileDecorations.fire(undefined);
    }
  }

  /**
   * Returns whether a blast radius is currently active.
   */
  isActive(): boolean {
    return this.sourceFile !== undefined;
  }

  /**
   * Returns the list of affected files in the current blast radius.
   */
  getAffectedFiles(): string[] {
    return Array.from(this.affectedFilesSet);
  }

  /**
   * Returns the source file of the current blast radius, if active.
   */
  getSourceFile(): string | undefined {
    return this.sourceFile;
  }

  /**
   * Provides a FileDecoration for blast radius visualization.
   * Returns an orange decoration for affected files when active.
   */
  provideFileDecoration(
    uri: vscode.Uri,
  ): vscode.FileDecoration | undefined {
    if (!this.isActive()) {
      return undefined;
    }

    const relativePath = this.toRelativePath(uri);
    if (relativePath === undefined) {
      return undefined;
    }

    // Decorate the source file
    if (relativePath === this.sourceFile) {
      const decoration = new vscode.FileDecoration(
        "\u25CE",
        "Blast radius source",
        new vscode.ThemeColor("noLongerVibe.flagged"),
      );
      decoration.propagate = false;
      return decoration;
    }

    // Decorate affected files
    if (this.affectedFilesSet.has(relativePath)) {
      const decoration = new vscode.FileDecoration(
        "!",
        "In blast radius — transitively affected",
        new vscode.ThemeColor("noLongerVibe.flagged"),
      );
      decoration.propagate = false;
      return decoration;
    }

    return undefined;
  }

  /**
   * Subscribes to MCP tool events that affect blast radius.
   * Returns an array of Disposables for cleanup.
   */
  subscribeMcpEvents(
    toolEvent: vscode.Event<McpToolEvent>,
  ): vscode.Disposable[] {
    const disposables: vscode.Disposable[] = [];

    disposables.push(
      toolEvent((event) => {
        switch (event.tool) {
          case "show_blast_radius":
            if (typeof event.params.symbol === "string") {
              this.showBlastRadius(event.params.symbol);
            }
            break;
          case "clear_blast_radius":
          case "clear_all":
            this.clearBlastRadius();
            break;
        }
      }),
    );

    return disposables;
  }

  /**
   * Disposes the event emitter.
   */
  dispose(): void {
    this._onDidChangeFileDecorations.dispose();
  }

  // --- Private helpers ---

  private toRelativePath(uri: vscode.Uri): string | undefined {
    const filePath = uri.fsPath ?? uri.path;
    const root = this.workspaceRoot;

    if (!filePath.startsWith(root)) {
      return undefined;
    }

    const relative = filePath.slice(root.length);
    if (relative.startsWith("/")) {
      return relative.slice(1);
    }
    return relative;
  }
}
