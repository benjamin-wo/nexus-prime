import "@fontsource-variable/bricolage-grotesque/opsz.css";
import "@fontsource-variable/newsreader/opsz.css";
import "@fontsource-variable/newsreader/opsz-italic.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { startNative } from "./native";
import "./styles.css";
import { startMiniApp } from "./telegram";
import { watchViewport } from "./viewport";

startMiniApp();
startNative();
watchViewport();

const root = document.getElementById("root");
if (!root) throw new Error("#root missing");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
