/**
 * IPC bridge server — runs inside the VS Code extension process.
 *
 * Listens on a Unix domain socket for tool-call requests from the
 * standalone MCP server and forwards them to the extension's event
 * system.
 *
 * This module has NO vscode dependency so it can be tested standalone.
 */

import * as net from "node:net";
import * as fs from "node:fs";
import {
  type IpcRequest,
  type IpcResponse,
  MESSAGE_DELIMITER,
  encodeMessage,
} from "./ipcProtocol";

/** Callback invoked for each tool call received over the socket. */
export type ToolCallHandler = (
  tool: string,
  params: Record<string, unknown>,
) => Promise<{ content: Array<{ type: string; text: string }> }>;

/** Maximum buffer size per connection (1 MB). */
const MAX_BUFFER_SIZE = 1024 * 1024;

/** Tool names accepted over the IPC bridge. */
const ALLOWED_TOOLS = new Set([
  "highlight_range",
  "clear_highlights",
  "open_file",
  "mark_read",
  "mark_flagged",
  "set_codelens",
  "show_blast_radius",
  "clear_blast_radius",
  "update_progress_tree",
  "clear_all",
]);

export class IpcBridgeServer {
  private server: net.Server | undefined;
  private readonly socketPath: string;
  private readonly onToolCall: ToolCallHandler;
  private clients = new Set<net.Socket>();

  constructor(socketPath: string, onToolCall: ToolCallHandler) {
    this.socketPath = socketPath;
    this.onToolCall = onToolCall;
  }

  /** Start listening on the Unix domain socket. */
  async start(): Promise<void> {
    // Remove stale socket file if present
    if (fs.existsSync(this.socketPath)) {
      fs.unlinkSync(this.socketPath);
    }

    this.server = net.createServer((socket) => {
      this.clients.add(socket);
      socket.on("close", () => this.clients.delete(socket));
      this.handleConnection(socket);
    });

    return new Promise<void>((resolve, reject) => {
      this.server!.on("error", reject);
      this.server!.listen(this.socketPath, () => {
        resolve();
      });
    });
  }

  /** Stop the server, close all client connections, and clean up the socket file. */
  async stop(): Promise<void> {
    // Destroy all connected clients first
    for (const client of this.clients) {
      client.destroy();
    }
    this.clients.clear();

    return new Promise<void>((resolve) => {
      if (!this.server) {
        resolve();
        return;
      }

      this.server.close(() => {
        if (fs.existsSync(this.socketPath)) {
          fs.unlinkSync(this.socketPath);
        }
        this.server = undefined;
        resolve();
      });
    });
  }

  private handleConnection(socket: net.Socket): void {
    let buffer = "";

    // Swallow errors on client sockets — the "close" event
    // handles cleanup via the this.clients Set.
    socket.on("error", () => {});

    socket.on("data", (chunk: Buffer) => {
      if (buffer.length + chunk.length > MAX_BUFFER_SIZE) {
        socket.destroy();
        return;
      }

      buffer += chunk.toString();

      let delimiterIndex: number;
      while ((delimiterIndex = buffer.indexOf(MESSAGE_DELIMITER)) !== -1) {
        const rawMessage = buffer.slice(0, delimiterIndex);
        buffer = buffer.slice(delimiterIndex + MESSAGE_DELIMITER.length);

        if (rawMessage.length === 0) {
          continue;
        }

        this.processMessage(socket, rawMessage);
      }
    });
  }

  private processMessage(socket: net.Socket, raw: string): void {
    let request: IpcRequest;
    try {
      request = JSON.parse(raw) as IpcRequest;
    } catch {
      return; // Ignore malformed messages
    }

    if (!ALLOWED_TOOLS.has(request.tool)) {
      const response: IpcResponse = {
        id: request.id,
        error: `Unknown tool: ${request.tool}`,
      };
      if (!socket.destroyed) {
        socket.write(encodeMessage(response));
      }
      return;
    }

    this.onToolCall(request.tool, request.params)
      .then((result) => {
        const response: IpcResponse = {
          id: request.id,
          result,
        };
        if (!socket.destroyed) {
          socket.write(encodeMessage(response));
        }
      })
      .catch((err: unknown) => {
        const response: IpcResponse = {
          id: request.id,
          error: err instanceof Error ? err.message : String(err),
        };
        if (!socket.destroyed) {
          socket.write(encodeMessage(response));
        }
      });
  }
}
