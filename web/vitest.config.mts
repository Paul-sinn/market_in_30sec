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
  // 기존 테스트 = 가격 표시 on 동작(#56). off 테스트는 vi.stubEnv로 바꾸고 vi.unstubAllEnvs로 on에 돌아온다
  test: { include: ["tests/**/*.test.{ts,tsx}"], env: { PRICE_DISPLAY: "on" } },
});
