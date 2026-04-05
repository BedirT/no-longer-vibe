import * as vscode from "vscode";
import { dispose, loadMapData, watchMapJson } from "./mapData";
import { FileStatusDecorationProvider } from "./fileDecorationProvider";
import { createMcpServer } from "./mcpServer";

/**
 * Called by VS Code when the extension activates.
 * Activation event: workspaceContains:.codebase-guide/map.json
 */
export async function activate(
  context: vscode.ExtensionContext,
): Promise<void> {
  const outputChannel = vscode.window.createOutputChannel("No Longer Vibe");
  context.subscriptions.push(outputChannel);
  outputChannel.appendLine("No Longer Vibe extension activating...");

  // Load map.json on activation
  const mapData = await loadMapData();
  if (mapData) {
    outputChannel.appendLine(
      `Loaded codebase map: ${mapData.total_files} files across ${Object.keys(mapData.layers).length} layers`,
    );
  } else {
    outputChannel.appendLine(
      "No map.json found or failed to parse. Run /read-index to generate it.",
    );
  }

  // Watch for map.json changes
  const watcherDisposable = watchMapJson();
  context.subscriptions.push(watcherDisposable);

  // Register FileDecorationProvider for file status colors
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (workspaceFolders && workspaceFolders.length > 0) {
    const workspaceRoot = workspaceFolders[0].uri.fsPath;
    const decorationProvider = new FileStatusDecorationProvider(workspaceRoot);

    context.subscriptions.push(
      vscode.window.registerFileDecorationProvider(decorationProvider),
    );
    context.subscriptions.push(decorationProvider);

    // Subscribe to MCP tool events for decoration updates
    const { toolEvents } = createMcpServer();
    const mcpDisposables = decorationProvider.subscribeMcpEvents(
      toolEvents.event,
    );
    for (const d of mcpDisposables) {
      context.subscriptions.push(d);
    }

    outputChannel.appendLine("File decoration provider registered.");
  }

  outputChannel.appendLine("No Longer Vibe extension activated.");
}

/**
 * Called by VS Code when the extension deactivates.
 */
export function deactivate(): void {
  dispose();
}
