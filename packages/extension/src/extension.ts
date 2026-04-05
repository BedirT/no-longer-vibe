import * as vscode from "vscode";
import { dispose, loadMapData, watchMapJson } from "./mapData";

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

  outputChannel.appendLine("No Longer Vibe extension activated.");
}

/**
 * Called by VS Code when the extension deactivates.
 */
export function deactivate(): void {
  dispose();
}
