import { describe, it, expect } from "vitest";
import * as os from "node:os";
import { getSocketPath } from "../src/ipcProtocol";

describe("ipcProtocol", () => {
  describe("getSocketPath", () => {
    it("returns a socket path in the system temp directory", () => {
      const socketPath = getSocketPath("/home/user/my-project");
      expect(socketPath).toContain(os.tmpdir());
      expect(socketPath).toMatch(/nlv-[a-f0-9]+\.sock$/);
    });

    it("is deterministic — same input produces same output", () => {
      const a = getSocketPath("/home/user/my-project");
      const b = getSocketPath("/home/user/my-project");
      expect(a).toBe(b);
    });

    it("produces different paths for different workspace roots", () => {
      const a = getSocketPath("/home/user/project-a");
      const b = getSocketPath("/home/user/project-b");
      expect(a).not.toBe(b);
    });

    it("normalizes trailing slashes", () => {
      const a = getSocketPath("/home/user/project");
      const b = getSocketPath("/home/user/project/");
      expect(a).toBe(b);
    });
  });
});
