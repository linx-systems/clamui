import { createContext, useContext, useRef, useState, type ReactNode } from "react";

import { copyText } from "./api";
import { Icon } from "./Icon";
import { _ } from "./i18n";
import { Modal } from "./Modal";

export type ManualConfiguration = {
  readonly path: string;
  readonly content: string;
};

type ConfigurationRecoveryActions = {
  open: (configurations: readonly ManualConfiguration[]) => void;
  helperFailed: (rawError: string, configurations: readonly ManualConfiguration[]) => void;
  clear: () => void;
};

const ConfigurationRecoveryContext = createContext<ConfigurationRecoveryActions | null>(null);

export function ConfigurationRecoveryProvider({
  actions,
  children,
}: {
  actions: ConfigurationRecoveryActions;
  children: ReactNode;
}): ReactNode {
  return <ConfigurationRecoveryContext.Provider value={actions}>{children}</ConfigurationRecoveryContext.Provider>;
}

export function useConfigurationRecovery(): ConfigurationRecoveryActions {
  const actions = useContext(ConfigurationRecoveryContext);
  if (!actions) {
    throw new Error("Configuration recovery actions are unavailable.");
  }
  return actions;
}

export function ConfigurationRecoveryDialog({
  configurations,
  onClose,
}: {
  configurations: readonly ManualConfiguration[];
  onClose: () => void;
}): ReactNode {
  const copyInFlight = useRef(false);
  const [copying, setCopying] = useState(false);
  const [copyStatus, setCopyStatus] = useState<{ tone: "success" | "error"; message: string } | null>(null);
  const copy = async (text: string, successMessage: string, errorMessage: string): Promise<void> => {
    if (copyInFlight.current) {
      return;
    }
    copyInFlight.current = true;
    setCopying(true);
    setCopyStatus(null);
    try {
      await copyText(text);
      setCopyStatus({ tone: "success", message: successMessage });
    } catch {
      setCopyStatus({ tone: "error", message: errorMessage });
    } finally {
      copyInFlight.current = false;
      setCopying(false);
    }
  };

  return <Modal title={_("Configuration from failed save attempt")} onClose={onClose} className="configuration-recovery-dialog">
    <div className="configuration-recovery-content">
      <p>{_("These are the configuration contents from the failed save attempt. Some files may already have changed. Check each target before replacing its content.")}</p>
      <p className="configuration-recovery-caution"><Icon name="warning" />{_("Configuration contents may include sensitive values. Copy and store them carefully.")}</p>
      {copyStatus ? <p className={`notice ${copyStatus.tone} configuration-recovery-copy-status`} role={copyStatus.tone === "error" ? "alert" : "status"} aria-live={copyStatus.tone === "error" ? "assertive" : "polite"}>{copyStatus.message}</p> : null}
      <div className="configuration-recovery-files">
        {configurations.map((configuration, index) => <section className="configuration-recovery-file" key={`${configuration.path}-${index}`}>
          <div className="configuration-recovery-file-header">
            <code id={`configuration-recovery-path-${index}`}>{configuration.path}</code>
            <div className="actions">
              <button className="button" type="button" disabled={copying} onClick={() => void copy(
                configuration.path,
                _("Configuration path copied to clipboard"),
                _("Could not copy configuration path."),
              )}><Icon name="copy" />{_("Copy Path")}</button>
              <button className="button" type="button" disabled={copying} onClick={() => void copy(
                configuration.content,
                _("Configuration content copied to clipboard"),
                _("Could not copy configuration content."),
              )}><Icon name="copy" />{_("Copy Content")}</button>
            </div>
          </div>
          <textarea aria-label={_("Configuration content")} aria-describedby={`configuration-recovery-path-${index}`} readOnly spellCheck={false} value={configuration.content} />
        </section>)}
      </div>
    </div>
    <div className="dialog-actions configuration-recovery-actions">
      <button className="button primary" type="button" onClick={onClose}>{_("Close")}</button>
    </div>
  </Modal>;
}
