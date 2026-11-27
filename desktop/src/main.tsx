import "./startup";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { _, loadCatalog } from "./i18n";
import { StartupBoundary, StartupReady } from "./StartupBoundary";
import { bootMark, reportFrontend } from "./startup";
import "./styles.css";

bootMark("bundle evaluated");

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("ClamUI could not find its application root");
}

const root = createRoot(rootElement);
void loadCatalog()
  .then(() => {
    bootMark("catalog loaded");
    root.render(
      <StrictMode>
        <StartupBoundary>
          <App />
          <StartupReady />
        </StartupBoundary>
      </StrictMode>,
    );
  })
  .catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    bootMark("catalog failed");
    void reportFrontend("catalog", message);
    root.render(
      <main className="startup-error">
        <section className="card" aria-labelledby="startup-error-title">
          <h1 id="startup-error-title">{_("ClamUI could not start")}</h1>
          <p className="error">{message}</p>
          <button className="button primary" type="button" onClick={() => window.location.reload()}>
            {_("Retry")}
          </button>
        </section>
      </main>,
    );
  });
