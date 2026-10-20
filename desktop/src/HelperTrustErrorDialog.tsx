import { type ReactNode } from "react";

import { notify, openExternal } from "./api";
import { Icon } from "./Icon";
import { _ } from "./i18n";
import { Modal } from "./Modal";

const HELPER_PATH = "/usr/bin/clamui-apply-preferences";
const REPAIR_GUIDE_URL = "https://clamui.com/docs/troubleshooting/#privileged-helper-is-not-trusted";
const TRUST_FAILURES: Record<string, true> = {
  "the canonical privileged helper is not a root-owned immutable executable": true,
  "legacy privileged helper libraries are not root-owned and immutable": true,
};

function normalizedTrustFailure(message: string): string {
  let normalized = message.trim();
  while (normalized.startsWith("Error:")) {
    normalized = normalized.slice("Error:".length).trimStart();
  }
  return normalized.trim();
}

/** Recognizes the exact native helper trust failures without changing their fail-closed behavior. */
export function isHelperTrustError(message: string): boolean {
  return TRUST_FAILURES[normalizedTrustFailure(message)] === true;
}

type HelperTrustErrorDialogProps = {
  rawError: string;
  onClose: () => void;
};

export function HelperTrustErrorDialog({ rawError, onClose }: HelperTrustErrorDialogProps): ReactNode {
  const openRepairGuide = (): void => {
    void openExternal(REPAIR_GUIDE_URL).catch((error: unknown) => {
      notify(_("Could not open documentation: {error}", { error: String(error) }), "error");
    });
  };

  return <Modal title={_("Protected settings are blocked")} onClose={onClose} className="helper-trust-error-dialog">
    <section className="helper-trust-error-content">
      <div className="helper-trust-error-intro">
        <Icon name="warning" className="helper-trust-error-icon" />
        <div>
          <p>{_("ClamUI blocked this operation because its system helper is missing or is not securely installed.")}</p>
          <p>{_("The helper provides administrator-authorized access to protected ClamAV settings.")}</p>
        </div>
      </div>
      <div className="helper-trust-error-location">
        <strong>{_("Helper location")}</strong>
        <code>{HELPER_PATH}</code>
      </div>
      <p className="helper-trust-error-requirement">{_("The helper must be an executable file owned by root, not a symbolic link, and other users must not be able to change it.")}</p>
      <h3>{_("How to fix it")}</h3>
      <ol className="helper-trust-error-steps">
        <li>{_("Reinstall the matching helper from the same trusted ClamUI release.")}</li>
        <li>{_("Then return to Preferences and repeat the action.")}</li>
      </ol>
      <p className="helper-trust-error-caution"><Icon name="shield" />{_("Do not change the permissions of an unknown executable to bypass this check.")}</p>
      <details className="helper-trust-error-details">
        <summary tabIndex={0}><Icon name="chevron-down" />{_("Technical details")}</summary>
        <pre>{rawError}</pre>
      </details>
    </section>
    <div className="dialog-actions helper-trust-error-actions">
      <button className="button" type="button" onClick={openRepairGuide}><Icon name="external-link" />{_("Open repair instructions")}</button>
      <button className="button primary" type="button" onClick={onClose}>{_("Close")}</button>
    </div>
  </Modal>;
}
