import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { _, loadCatalog } from "./i18n";
import "./styles.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("ClamUI could not find its application root");
}

const root = createRoot(rootElement);
void loadCatalog()
  .then(() => {
    root.render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  })
  .catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
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
