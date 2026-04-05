/**
 * Shared IPC protocol for the bridge between the standalone MCP server
 * and the VS Code extension.
 *
 * This module has NO vscode dependency — it is imported by both the
 * extension (ipcServer) and the standalone server (ipcClient).
 */

import * as crypto from "node:crypto";
import * as path from "node:path";
import * as os from "node:os";

/** Request sent from the standalone MCP server to the extension. */
export interface IpcRequest {
  id: number;
  tool: string;
  params: Record<string, unknown>;
}

/** Response sent from the extension back to the standalone server. */
export interface IpcResponse {
  id: number;
  result?: { content: Array<{ type: string; text: string }> };
  error?: string;
}

/**
 * Computes a deterministic Unix domain socket path for a workspace.
 * Both the extension and the standalone server use this to find each
 * other without configuration.
 */
export function getSocketPath(workspaceRoot: string): string {
  const normalized = workspaceRoot.replace(/\/+$/, "");
  const hash = crypto
    .createHash("sha256")
    .update(normalized)
    .digest("hex")
    .slice(0, 16);
  return path.join(os.tmpdir(), `nlv-${hash}.sock`);
}

/** Sentinel used to delimit JSON messages on the socket. */
export const MESSAGE_DELIMITER = "\n";

/**
 * Encodes a message for transmission over the socket.
 */
export function encodeMessage(msg: IpcRequest | IpcResponse): string {
  return JSON.stringify(msg) + MESSAGE_DELIMITER;
}
