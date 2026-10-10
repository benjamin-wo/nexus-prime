import base from "/home/user/nexus-prime/web/playwright.config";
export default {
  ...base,
  testDir: "/home/user/nexus-prime/web/e2e",
  webServer: { ...(base.webServer as object), cwd: "/home/user/nexus-prime/web" },
  use: { ...base.use, launchOptions: { executablePath: "/opt/pw-browsers/chromium" } },
  projects: base.projects?.map((p) => ({ ...p, use: { ...p.use, launchOptions: { executablePath: "/opt/pw-browsers/chromium" } } })),
};
