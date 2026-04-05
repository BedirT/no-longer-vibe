/**
 * IPC bridge client — runs inside the standalone MCP server process.
 *
 * Connects to the VS Code extension's Unix domain socket and forwards
 * visual tool calls. Falls back gracefully when the extension is not
 * running.
 *
 * This module has NO vscode dependency.
 */

import * as net from "node:net";
import {
  type IpcRequest,
  type IpcResponse,
  MESSAGE_DELIMITER,
  encodeMessage,
} from "./ipcProtocol";

/** Timeout for individual tool call round-trips (ms). */
const CALL_TIMEOUT = 5000;

/** Timeout for the initial connection attempt (ms). */
const CONNECT_TIMEOUT = 1000;

/** Maximum buffer size for incoming data (1 MB). */
const MAX_BUFFER_SIZE = 1024 * 1024;

export class IpcBridgeClient {
  private socket: net.Socket | undefined;
  private connected = false;
  private readonly socketPath: string;
  private nextId = 1;
  private pending = new Map<
    number,
    {
      resolve: (value: IpcResponse | undefined) => void;
      timer: ReturnType<typeof setTimeout>;
    }
  >();
  private buffer = "";

  constructor(socketPath: string) {
    this.socketPath = socketPath;
  }

  /**
   * Attempts to connect to the extension's IPC server.
   * Returns true if the connection succeeded, false otherwise.
   */
  async connect(): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      const socket = net.createConnection({ path: this.socketPath });

      const timeout = setTimeout(() => {
        socket.destroy();
        resolve(false);
      }, CONNECT_TIMEOUT);

      socket.on("connect", () => {
        clearTimeout(timeout);
        this.socket = socket;
        this.connected = true;
        this.setupSocketHandlers(socket);
        resolve(true);
      });

      socket.on("error", () => {
        clearTimeout(timeout);
        this.connected = false;
        resolve(false);
      });
    });
  }

  /** Whether the client is currently connected to the extension. */
  isConnected(): boolean {
    return this.connected;
  }

  /**
   * Forwards a tool call to the extension via the IPC socket.
   * Returns the result, or undefined if not connected or on error.
   */
  async callTool(
    tool: string,
    params: Record<string, unknown>,
  ): Promise<{ content: Array<{ type: string; text: string }> } | undefined> {
    if (!this.connected || !this.socket) {
      return undefined;
    }

    const id = this.nextId++;
    const request: IpcRequest = { id, tool, params };

    return new Promise<
      { content: Array<{ type: string; text: string }> } | undefined
    >((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        resolve(undefined);
      }, CALL_TIMEOUT);

      this.pending.set(id, {
        resolve: (resp: IpcResponse | undefined) => {
          clearTimeout(timer);
          this.pending.delete(id);
          if (resp?.result) {
            resolve(resp.result);
          } else {
            resolve(undefined);
          }
        },
        timer,
      });

      this.socket!.write(encodeMessage(request));
    });
  }

  /** Disconnect from the extension. */
  disconnect(): void {
    this.connected = false;

    // Resolve all pending calls
    for (const [, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.resolve(undefined);
    }
    this.pending.clear();

    if (this.socket) {
      this.socket.destroy();
      this.socket = undefined;
    }
  }

  private setupSocketHandlers(socket: net.Socket): void {
    socket.on("data", (chunk: Buffer) => {
      if (this.buffer.length + chunk.length > MAX_BUFFER_SIZE) {
        socket.destroy();
        return;
      }
      this.buffer += chunk.toString();

      let delimiterIndex: number;
      while (
        (delimiterIndex = this.buffer.indexOf(MESSAGE_DELIMITER)) !== -1
      ) {
        const rawMessage = this.buffer.slice(0, delimiterIndex);
        this.buffer = this.buffer.slice(
          delimiterIndex + MESSAGE_DELIMITER.length,
        );

        if (rawMessage.length === 0) {
          continue;
        }

        try {
          const response = JSON.parse(rawMessage) as IpcResponse;
          const entry = this.pending.get(response.id);
          if (entry) {
            entry.resolve(response);
          }
        } catch {
          // Ignore malformed responses
        }
      }
    });

    socket.on("close", () => {
      this.connected = false;
      // Resolve all pending calls on disconnect
      for (const [, entry] of this.pending) {
        clearTimeout(entry.timer);
        entry.resolve(undefined);
      }
      this.pending.clear();
    });

    socket.on("error", () => {
      this.connected = false;
    });
  }
}
