import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // server-only는 react-server 조건 밖에서 import하면 throw한다. 테스트는 그 패키지의 빈 파일을 쓴다
      "server-only": fileURLToPath(new URL("./node_modules/server-only/empty.js", import.meta.url)),
    },
  },
  test: { include: ["tests/**/*.test.{ts,tsx}"] },
});
