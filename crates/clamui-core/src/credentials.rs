use crate::{AppResult, Context};
use secret_service::{blocking::SecretService, EncryptionType};
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::HashMap;

pub const SERVICE_NAME: &str = "clamui";
pub const VIRUSTOTAL_API_KEY: &str = "virustotal_api_key";
pub const PORTMASTER_API_TOKEN: &str = "portmaster_api_token";
const PLAINTEXT_FALLBACK_SETTING: &str = "allow_plaintext_api_key_fallback";

/// The only account names ClamUI stores. Keeping this closed prevents this
/// module from becoming a generic secret exfiltration API.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Account {
    VirusTotalApiKey,
    PortmasterApiToken,
}

impl Account {
    pub const fn username(self) -> &'static str {
        match self {
            Self::VirusTotalApiKey => VIRUSTOTAL_API_KEY,
            Self::PortmasterApiToken => PORTMASTER_API_TOKEN,
        }
    }

    const fn fallback_setting(self) -> &'static str {
        self.username()
    }

    const fn label(self) -> &'static str {
        match self {
            Self::VirusTotalApiKey => "ClamUI VirusTotal API key",
            Self::PortmasterApiToken => "ClamUI Portmaster API token",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CredentialBackend {
    Keyring,
    PlaintextFallback,
    None,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CredentialStatus {
    Configured,
    NotConfigured,
    Locked,
    Unavailable,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct CredentialInfo {
    pub present: bool,
    pub backend: CredentialBackend,
    pub status: CredentialStatus,
    pub masked: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CredentialWrite {
    pub backend: CredentialBackend,
    pub warning: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum KeyringFailure {
    Locked,
    Unavailable,
}

/// Uses the existing Python-keyring compatible Secret Service attribute set.
pub fn attributes(account: Account) -> HashMap<&'static str, &'static str> {
    HashMap::from([("service", SERVICE_NAME), ("username", account.username())])
}

pub fn validate_virustotal_api_key(key: &str) -> AppResult<()> {
    if key.is_empty() {
        return Err("API key cannot be empty".into());
    }
    if key.len() != 64 {
        return Err(format!("API key must be 64 characters (got {})", key.len()));
    }
    if !key.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("API key must contain only hexadecimal characters".into());
    }
    Ok(())
}
pub fn mask_api_key(key: Option<&str>) -> String {
    match key {
        None | Some("") => "Not set".into(),
        Some(key) if key.chars().count() < 8 => "****".into(),
        Some(key) => format!("{}...", key.chars().take(8).collect::<String>()),
    }
}

pub struct CredentialStore {
    ctx: Context,
}

impl CredentialStore {
    pub fn new(ctx: &Context) -> Self {
        Self { ctx: ctx.clone() }
    }

    pub fn get(&self, account: Account) -> AppResult<Option<String>> {
        match keyring_get(account) {
            Ok(Some(secret)) => Ok(Some(secret)),
            Ok(None) | Err(_) => self.fallback_get(account),
        }
    }

    pub fn status(&self, account: Account) -> AppResult<CredentialInfo> {
        match keyring_get(account) {
            Ok(Some(secret)) => Ok(CredentialInfo {
                present: true,
                backend: CredentialBackend::Keyring,
                status: CredentialStatus::Configured,
                masked: (account == Account::VirusTotalApiKey).then(|| mask_api_key(Some(&secret))),
            }),
            Ok(None) => self.fallback_status(account, None),
            Err(KeyringFailure::Locked) => {
                self.fallback_status(account, Some(CredentialStatus::Locked))
            }
            Err(KeyringFailure::Unavailable) => {
                self.fallback_status(account, Some(CredentialStatus::Unavailable))
            }
        }
    }

    pub fn set(&self, account: Account, secret: &str) -> AppResult<CredentialWrite> {
        if secret.is_empty() {
            return Err(if account == Account::VirusTotalApiKey {
                "API key cannot be empty".into()
            } else {
                "Token cannot be empty".into()
            });
        }
        if account == Account::VirusTotalApiKey {
            validate_virustotal_api_key(secret)?;
        }

        match keyring_set(account, secret) {
            Ok(()) => Ok(CredentialWrite {
                backend: CredentialBackend::Keyring,
                warning: None,
            }),
            Err(KeyringFailure::Locked) => Err("System keyring is locked".into()),
            Err(KeyringFailure::Unavailable) if self.plaintext_fallback_allowed()? => {
                self.ctx.update_settings(json!({account.fallback_setting(): secret}))?;
                Ok(CredentialWrite {
                    backend: CredentialBackend::PlaintextFallback,
                    warning: Some(crate::i18n::translate(
                        &self.ctx,
                        // Translators: The em dash separates the fallback state from its security warning.
                        "Stored in settings file (keyring unavailable — less secure)",
                    )),
                })
            }
            Err(KeyringFailure::Unavailable) => Err(
                "System keyring is unavailable. To store this credential without a keyring, enable the plaintext fallback in preferences (less secure).".into(),
            ),
        }
    }
    /// Delete is deliberately best-effort per backing store, but a settings
    /// write error remains visible because a plaintext secret could remain.
    pub fn delete(&self, account: Account) -> AppResult<bool> {
        let keyring_deleted = keyring_delete(account).unwrap_or(false);
        let fallback_deleted = self.clear_fallback(account)?;
        Ok(keyring_deleted || fallback_deleted)
    }

    fn fallback_get(&self, account: Account) -> AppResult<Option<String>> {
        let settings = self.ctx.settings()?;
        Ok(settings
            .get(account.fallback_setting())
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .map(str::to_owned))
    }

    fn fallback_status(
        &self,
        account: Account,
        unavailable_status: Option<CredentialStatus>,
    ) -> AppResult<CredentialInfo> {
        let secret = self.fallback_get(account)?;
        let present = secret.is_some();
        Ok(CredentialInfo {
            present,
            backend: if present {
                CredentialBackend::PlaintextFallback
            } else {
                CredentialBackend::None
            },
            status: if present {
                CredentialStatus::Configured
            } else {
                unavailable_status.unwrap_or(CredentialStatus::NotConfigured)
            },
            masked: (account == Account::VirusTotalApiKey && present)
                .then(|| mask_api_key(secret.as_deref())),
        })
    }

    fn plaintext_fallback_allowed(&self) -> AppResult<bool> {
        Ok(self
            .ctx
            .settings()?
            .get(PLAINTEXT_FALLBACK_SETTING)
            .and_then(Value::as_bool)
            .unwrap_or(false))
    }

    fn clear_fallback(&self, account: Account) -> AppResult<bool> {
        let existed = self
            .ctx
            .settings()?
            .get(account.fallback_setting())
            .is_some_and(|value| !value.is_null());
        self.ctx
            .update_settings(json!({account.fallback_setting(): Value::Null}))?;
        Ok(existed)
    }
}

fn keyring_get(account: Account) -> Result<Option<String>, KeyringFailure> {
    let service =
        SecretService::connect(EncryptionType::Dh).map_err(|_| KeyringFailure::Unavailable)?;
    let items = service
        .search_items(attributes(account))
        .map_err(|_| KeyringFailure::Unavailable)?;
    if let Some(item) = items.unlocked.first() {
        let secret = item.get_secret().map_err(|_| KeyringFailure::Unavailable)?;
        return String::from_utf8(secret)
            .map(Some)
            .map_err(|_| KeyringFailure::Unavailable);
    }
    if !items.locked.is_empty() {
        return Err(KeyringFailure::Locked);
    }
    Ok(None)
}

fn keyring_set(account: Account, secret: &str) -> Result<(), KeyringFailure> {
    let service =
        SecretService::connect(EncryptionType::Dh).map_err(|_| KeyringFailure::Unavailable)?;
    let collection = service
        .get_default_collection()
        .map_err(|_| KeyringFailure::Unavailable)?;
    if collection
        .is_locked()
        .map_err(|_| KeyringFailure::Unavailable)?
    {
        return Err(KeyringFailure::Locked);
    }
    collection
        .create_item(
            account.label(),
            attributes(account),
            secret.as_bytes(),
            true,
            "text/plain",
        )
        .map(|_| ())
        .map_err(|_| KeyringFailure::Unavailable)
}

fn keyring_delete(account: Account) -> Result<bool, KeyringFailure> {
    let service =
        SecretService::connect(EncryptionType::Dh).map_err(|_| KeyringFailure::Unavailable)?;
    let items = service
        .search_items(attributes(account))
        .map_err(|_| KeyringFailure::Unavailable)?;
    if !items.locked.is_empty() {
        return Err(KeyringFailure::Locked);
    }
    let mut deleted = false;
    for item in items.unlocked {
        item.delete().map_err(|_| KeyringFailure::Unavailable)?;
        deleted = true;
    }
    Ok(deleted)
}

pub fn get_portmaster_token(ctx: &Context) -> AppResult<Option<String>> {
    CredentialStore::new(ctx).get(Account::PortmasterApiToken)
}

pub fn set_portmaster_token(ctx: &Context, token: &str) -> AppResult<CredentialWrite> {
    CredentialStore::new(ctx).set(Account::PortmasterApiToken, token)
}

pub fn delete_portmaster_token(ctx: &Context) -> AppResult<bool> {
    CredentialStore::new(ctx).delete(Account::PortmasterApiToken)
}
