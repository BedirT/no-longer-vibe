import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";
import { IpcBridgeServer } from "../src/ipcServer";
import { IpcBridgeClient } from "../src/ipcClient";

describe("IPC Bridge", () => {
  let tmpDir: string;
  let socketPath: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "nlv-ipc-test-"));
    socketPath = path.join(tmpDir, "test.sock");
  });

  afterEach(async () => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  describe("IpcBridgeServer", () => {
    it("starts and listens on the socket path", async () => {
      const server = new IpcBridgeServer(socketPath, async () => ({
        content: [{ type: "text", text: "ok" }],
      }));

      await server.start();
      expect(fs.existsSync(socketPath)).toBe(true);
      await server.stop();
    });

    it("cleans up socket file on stop", async () => {
      const server = new IpcBridgeServer(socketPath, async () => ({
        content: [{ type: "text", text: "ok" }],
      }));

      await server.start();
      await server.stop();
      expect(fs.existsSync(socketPath)).toBe(false);
    });

    it("removes stale socket file on start", async () => {
      // Create a stale socket file
      fs.writeFileSync(socketPath, "stale");

      const server = new IpcBridgeServer(socketPath, async () => ({
        content: [{ type: "text", text: "ok" }],
      }));

      await server.start();
      expect(fs.existsSync(socketPath)).toBe(true);
      await server.stop();
    });
  });

  describe("IpcBridgeClient", () => {
    it("reports disconnected when no server is running", async () => {
      const client = new IpcBridgeClient(socketPath);
      const connected = await client.connect();
      expect(connected).toBe(false);
      expect(client.isConnected()).toBe(false);
    });

    it("connects to a running server", async () => {
      const server = new IpcBridgeServer(socketPath, async () => ({
        content: [{ type: "text", text: "ok" }],
      }));
      await server.start();

      const client = new IpcBridgeClient(socketPath);
      const connected = await client.connect();
      expect(connected).toBe(true);
      expect(client.isConnected()).toBe(true);

      client.disconnect();
      await server.stop();
    });

    it("detects disconnection when server stops", async () => {
      const server = new IpcBridgeServer(socketPath, async () => ({
        content: [{ type: "text", text: "ok" }],
      }));
      await server.start();

      const client = new IpcBridgeClient(socketPath);
      await client.connect();
      expect(client.isConnected()).toBe(true);

      await server.stop();

      // Give the client time to detect the disconnection
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(client.isConnected()).toBe(false);

      client.disconnect();
    });
  });

  describe("end-to-end tool forwarding", () => {
    it("forwards a tool call and returns the result", async () => {
      const handler = async (
        tool: string,
        params: Record<string, unknown>,
      ) => ({
        content: [
          {
            type: "text" as const,
            text: `Handled ${tool} with ${JSON.stringify(params)}`,
          },
        ],
      });

      const server = new IpcBridgeServer(socketPath, handler);
      await server.start();

      const client = new IpcBridgeClient(socketPath);
      await client.connect();

      const result = await client.callTool("highlight_range", {
        file: "src/main.ts",
        startLine: 10,
        endLine: 20,
        style: "focus",
      });

      expect(result).toBeDefined();
      expect(result!.content[0].text).toContain("highlight_range");
      expect(result!.content[0].text).toContain("src/main.ts");

      client.disconnect();
      await server.stop();
    });

    it("forwards multiple sequential tool calls", async () => {
      let callCount = 0;
      const handler = async (tool: string) => {
        callCount++;
        return {
          content: [{ type: "text" as const, text: `Call ${callCount}: ${tool}` }],
        };
      };

      const server = new IpcBridgeServer(socketPath, handler);
      await server.start();

      const client = new IpcBridgeClient(socketPath);
      await client.connect();

      const r1 = await client.callTool("highlight_range", { file: "a.ts", startLine: 1, endLine: 2, style: "focus" });
      const r2 = await client.callTool("clear_highlights", {});
      const r3 = await client.callTool("open_file", { path: "b.ts" });

      expect(r1!.content[0].text).toBe("Call 1: highlight_range");
      expect(r2!.content[0].text).toBe("Call 2: clear_highlights");
      expect(r3!.content[0].text).toBe("Call 3: open_file");

      client.disconnect();
      await server.stop();
    });

    it("returns undefined when not connected", async () => {
      const client = new IpcBridgeClient(socketPath);
      // Don't connect

      const result = await client.callTool("highlight_range", {
        file: "src/main.ts",
        startLine: 1,
        endLine: 5,
        style: "focus",
      });

      expect(result).toBeUndefined();
    });

    it("handles concurrent tool calls correctly", async () => {
      const handler = async (tool: string) => ({
        content: [{ type: "text" as const, text: tool }],
      });

      const server = new IpcBridgeServer(socketPath, handler);
      await server.start();

      const client = new IpcBridgeClient(socketPath);
      await client.connect();

      const results = await Promise.all([
        client.callTool("highlight_range", { file: "a.ts", startLine: 1, endLine: 2, style: "focus" }),
        client.callTool("clear_highlights", {}),
        client.callTool("clear_all", {}),
      ]);

      expect(results[0]!.content[0].text).toBe("highlight_range");
      expect(results[1]!.content[0].text).toBe("clear_highlights");
      expect(results[2]!.content[0].text).toBe("clear_all");

      client.disconnect();
      await server.stop();
    });

    it("rejects unknown tool names", async () => {
      const handler = async () => ({
        content: [{ type: "text" as const, text: "should not reach" }],
      });

      const server = new IpcBridgeServer(socketPath, handler);
      await server.start();

      const client = new IpcBridgeClient(socketPath);
      await client.connect();

      const result = await client.callTool("unknown_tool", {});
      expect(result).toBeUndefined();

      client.disconnect();
      await server.stop();
    });

    it("handles handler errors gracefully", async () => {
      const handler = async () => {
        throw new Error("Handler failed");
      };

      const server = new IpcBridgeServer(socketPath, handler);
      await server.start();

      const client = new IpcBridgeClient(socketPath);
      await client.connect();

      // Use an allowed tool name so the request reaches the throwing handler
      const result = await client.callTool("highlight_range", {
        file: "a.ts",
        startLine: 1,
        endLine: 2,
        style: "focus",
      });
      expect(result).toBeUndefined();

      client.disconnect();
      await server.stop();
    });
  });
});
