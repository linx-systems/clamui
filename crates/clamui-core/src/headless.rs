//! Signal-aware context setup for long-running headless operations.
//!
//! Desktop contexts deliberately do not use this guard. It is for standalone
//! command processes that must turn Ctrl+C into cooperative job cancellation.

use std::{
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    thread::{self, JoinHandle},
};

use signal_hook::{
    consts::signal::SIGINT,
    iterator::{Handle, Signals},
};

use crate::{AppResult, Context};

/// Owns a headless context and its scoped SIGINT listener.
///
/// The interrupt latch is installed on the context before signal registration.
/// `Context::job` observes that latch while holding its job registry lock, so a
/// Ctrl+C delivered before or during job registration cannot be lost.
pub struct HeadlessContext {
    context: Context,
    signal_handle: Handle,
    signal_worker: Option<JoinHandle<()>>,
}

impl HeadlessContext {
    /// Creates a context that cooperatively cancels all of its jobs on SIGINT.
    pub fn new() -> AppResult<Self> {
        let latch = Arc::new(AtomicBool::new(false));
        let context = Context::new()?.with_interrupt_latch(Arc::clone(&latch));
        let mut signals = Signals::new([SIGINT])
            .map_err(|error| format!("cannot register SIGINT handler: {error}"))?;
        let signal_handle = signals.handle();
        let signal_context = context.clone();
        let signal_worker = thread::Builder::new()
            .name("clamui-headless-sigint".to_owned())
            .spawn(move || {
                for _ in signals.forever() {
                    latch.store(true, Ordering::Release);
                    signal_context.cancel_all();
                }
            })
            .map_err(|error| format!("cannot start SIGINT handler: {error}"))?;

        Ok(Self {
            context,
            signal_handle,
            signal_worker: Some(signal_worker),
        })
    }

    /// Returns the guarded context for the duration of this value's lifetime.
    pub fn context(&self) -> &Context {
        &self.context
    }
}

impl Drop for HeadlessContext {
    fn drop(&mut self) {
        self.signal_handle.close();
        if let Some(worker) = self.signal_worker.take() {
            let _ = worker.join();
        }
    }
}
