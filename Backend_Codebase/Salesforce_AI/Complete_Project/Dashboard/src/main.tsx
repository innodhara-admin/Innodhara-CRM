import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "./ui/tokens.css";
import { App } from "./app/router";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
