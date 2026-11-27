//! Startup timeline and watchdog.
//!
//! A blank or gray window has several indistinguishable causes: native startup
//! stuck before the window exists, a blocked UI thread, a bundle that never
//! ran, a React render error, or IPC that never answers. WebKit prints no
//! JavaScript errors to stderr, so none of them leaves a trace by default. This
//! module records a small in-memory timeline of native milestones, lets the
//! frontend report when it has mounted, and, if it has not within
//! [`WATCHDOG_DELAY`], writes one WARNING that says which stage was reached.
//!
//! Nothing here touches the filesystem or the network on a healthy start. Set
//! `CLAMUI_STARTUP_TRACE=1` to also echo every milestone to stderr.

use std::{
    sync::{
        atomic::{AtomicBool, AtomicUsize, Ordering},
        mpsc, Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};
use tauri::AppHandle;

/// How long the frontend gets to report that it mounted.
pub const WATCHDOG_DELAY: Duration = Duration::from_secs(10);
/// How long a task queued on the main thread gets to run before the UI thread
/// is considered blocked.
const MAIN_THREAD_PROBE: Duration = Duration::from_secs(3);
/// The watchdog keeps watching this long after its warning to note a late start.
const LATE_START_WINDOW: Duration = Duration::from_secs(300);
const MAX_MILESTONES: usize = 64;
const MAX_REPORTS: usize = 20;
const MAX_REPORT_CHARS: usize = 2000;

/// Kinds of report the frontend may send. Anything else is rejected.
const REPORT_KINDS: [&str; 5] = [
    "boot-error",
    "boot-stalled",
    "catalog",
    "render",
    "ready-failed",
];

pub struct StartupTrace {
    started: Instant,
    milestones: Mutex<Vec<(Duration, String)>>,
    setup_finished: AtomicBool,
    frontend_ready: AtomicBool,
    first_request: AtomicBool,
    first_response: AtomicBool,
    reports: AtomicUsize,
    echo: bool,
}

impl StartupTrace {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            started: Instant::now(),
            milestones: Mutex::new(Vec::new()),
            setup_finished: AtomicBool::new(false),
            frontend_ready: AtomicBool::new(false),
            first_request: AtomicBool::new(false),
            first_response: AtomicBool::new(false),
            reports: AtomicUsize::new(0),
            echo: std::env::var_os("CLAMUI_STARTUP_TRACE").is_some_and(|value| value != "0"),
        })
    }

    pub fn mark(&self, name: impl Into<String>) {
        let name = name.into();
        let elapsed = self.started.elapsed();
        if self.echo {
            eprintln!("ClamUI startup +{}ms {name}", elapsed.as_millis());
        }
        let mut milestones = self.milestones.lock().unwrap_or_else(|p| p.into_inner());
        if milestones.len() < MAX_MILESTONES {
            milestones.push((elapsed, name));
        }
    }

    /// Note the first IPC request that reaches Rust. Later calls are free.
    pub fn note_request(&self, action: &str) {
        if !self.first_request.swap(true, Ordering::AcqRel) {
            self.mark(format!("first IPC request received ({action})"));
        }
    }

    /// Note the first IPC request that Rust finished answering.
    pub fn note_response(&self, action: &str, succeeded: bool) {
        if !self.first_response.swap(true, Ordering::AcqRel) {
            let outcome = if succeeded { "ok" } else { "error" };
            self.mark(format!("first IPC request answered ({action}: {outcome})"));
        }
    }

    /// Record that `setup()` ran to its end. The main window exists long before
    /// that, so the watchdog cannot infer completion from the window handle.
    pub fn setup_finished(&self) {
        self.setup_finished.store(true, Ordering::Release);
        self.mark("setup finished");
    }

    pub fn is_setup_finished(&self) -> bool {
        self.setup_finished.load(Ordering::Acquire)
    }

    /// Record that the frontend mounted. Returns `true` the first time.
    pub fn frontend_ready(&self) -> bool {
        let first = !self.frontend_ready.swap(true, Ordering::AcqRel);
        if first {
            self.mark("frontend mounted");
        }
        first
    }

    pub fn is_ready(&self) -> bool {
        self.frontend_ready.load(Ordering::Acquire)
    }

    pub fn elapsed(&self) -> Duration {
        self.started.elapsed()
    }

    /// `true` while the frontend may still send a report.
    pub fn take_report_slot(&self) -> bool {
        self.reports.fetch_add(1, Ordering::AcqRel) < MAX_REPORTS
    }

    pub fn last_milestone(&self) -> String {
        self.milestones
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .last()
            .map(|(_, name)| name.clone())
            .unwrap_or_else(|| "none".into())
    }

    pub fn summary(&self) -> String {
        self.milestones
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .iter()
            .map(|(elapsed, name)| format!("+{}ms {name}", elapsed.as_millis()))
            .collect::<Vec<_>>()
            .join("; ")
    }
}

/// Validate a frontend report. The frontend is untrusted: the kind is an
/// allowlist and the text is stripped of control characters and truncated.
pub fn sanitize_report(kind: &str, message: &str) -> Result<(String, String), String> {
    if !REPORT_KINDS.contains(&kind) {
        return Err("unknown report kind".into());
    }
    let cleaned: String = message
        .chars()
        .map(|character| {
            if character.is_control() {
                ' '
            } else {
                character
            }
        })
        .take(MAX_REPORT_CHARS)
        .collect();
    Ok((kind.to_owned(), cleaned))
}

/// Where the startup got stuck, derived from what the watchdog can observe.
#[derive(Debug, PartialEq, Eq)]
pub enum Verdict {
    /// `setup()` had not reached its end: native startup itself is stuck, whether
    /// before the window exists or in a later step such as the accent colour,
    /// notification actions, device monitor or profile sync.
    SetupUnfinished,
    /// `setup()` finished, but a task queued on the main thread did not run: the
    /// UI thread is blocked afterwards.
    MainThreadBlocked,
    /// The main thread is alive but the frontend never mounted.
    FrontendMissing,
    /// The probe could not be queued (the event loop is gone).
    Unknown,
}

pub fn describe(verdict: &Verdict, last_milestone: &str) -> String {
    match verdict {
        Verdict::SetupUnfinished => format!(
            "native startup did not finish; the last milestone was \"{last_milestone}\". \
             Something in or before setup() is blocking"
        ),
        Verdict::MainThreadBlocked => format!(
            "the UI thread did not run a queued task within {}s (last milestone \"{last_milestone}\"). \
             It is blocked, typically in a synchronous call such as D-Bus, a portal or accessibility",
            MAIN_THREAD_PROBE.as_secs()
        ),
        Verdict::FrontendMissing => format!(
            "native startup finished and the UI thread is responsive (last milestone \"{last_milestone}\"), \
             but the web page never reported that it mounted. Check the web view: bundle load, \
             JavaScript error, or IPC that never answers"
        ),
        Verdict::Unknown => format!(
            "could not probe the UI thread (last milestone \"{last_milestone}\")"
        ),
    }
}

/// Watch for a frontend that never mounts. Runs on its own thread so that it
/// still fires when the UI thread is the thing that is stuck.
pub fn spawn_watchdog(
    trace: Arc<StartupTrace>,
    app_slot: Arc<Mutex<Option<AppHandle>>>,
    log: impl Fn(&str, &str) + Send + 'static,
) {
    let _ = thread::Builder::new()
        .name("clamui-startup-watchdog".into())
        .spawn(move || {
            let poll = Duration::from_millis(100);
            while trace.elapsed() < WATCHDOG_DELAY {
                if trace.is_ready() {
                    return;
                }
                thread::sleep(poll);
            }
            if trace.is_ready() {
                return;
            }
            let handle = app_slot.lock().unwrap_or_else(|p| p.into_inner()).clone();
            let verdict = pick_verdict(trace.is_setup_finished(), handle, |app| {
                probe_main_thread(&app)
            });
            let message = format!(
                "ClamUI window is not showing content after {}s: {}. Timeline: {}",
                WATCHDOG_DELAY.as_secs(),
                describe(&verdict, &trace.last_milestone()),
                trace.summary()
            );
            eprintln!("{message}");
            log("WARNING", &message);

            let deadline = trace.elapsed() + LATE_START_WINDOW;
            while trace.elapsed() < deadline {
                if trace.is_ready() {
                    let late = format!(
                        "frontend mounted late, {}ms after start",
                        trace.elapsed().as_millis()
                    );
                    eprintln!("ClamUI {late}");
                    log("WARNING", &late);
                    return;
                }
                thread::sleep(Duration::from_millis(250));
            }
        });
}

/// The window handle is stored right after the window is built, which is well
/// before `setup()` ends, so it only tells that the window exists. While setup
/// has not finished, the verdict is `SetupUnfinished` and the main thread is
/// not probed: a hang in a late setup step blocks the main thread too, and
/// would otherwise be reported as a blocked UI thread.
fn pick_verdict<T>(
    setup_finished: bool,
    handle: Option<T>,
    probe: impl FnOnce(T) -> Verdict,
) -> Verdict {
    match handle {
        Some(app) if setup_finished => probe(app),
        _ => Verdict::SetupUnfinished,
    }
}

fn probe_main_thread(app: &AppHandle) -> Verdict {
    let (sender, receiver) = mpsc::channel();
    if app
        .run_on_main_thread(move || {
            let _ = sender.send(());
        })
        .is_err()
    {
        return Verdict::Unknown;
    }
    match receiver.recv_timeout(MAIN_THREAD_PROBE) {
        Ok(()) => Verdict::FrontendMissing,
        Err(_) => Verdict::MainThreadBlocked,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn report_rejects_unknown_kinds() {
        assert!(sanitize_report("rm -rf", "x").is_err());
        assert!(sanitize_report("", "x").is_err());
        assert!(sanitize_report("render", "x").is_ok());
    }

    #[test]
    fn report_strips_control_characters_and_truncates() {
        let noisy = format!("line one\nline\ttwo\u{1b}[31m{}", "x".repeat(5000));
        let (_, cleaned) = sanitize_report("boot-error", &noisy).expect("valid kind");
        assert!(!cleaned.chars().any(char::is_control));
        assert_eq!(cleaned.chars().count(), MAX_REPORT_CHARS);
    }

    #[test]
    fn report_slots_are_bounded() {
        let trace = StartupTrace::new();
        let granted = (0..MAX_REPORTS + 10)
            .filter(|_| trace.take_report_slot())
            .count();
        assert_eq!(granted, MAX_REPORTS);
    }

    #[test]
    fn timeline_is_bounded_and_ordered() {
        let trace = StartupTrace::new();
        for index in 0..MAX_MILESTONES + 10 {
            trace.mark(format!("step {index}"));
        }
        let summary = trace.summary();
        assert!(summary.starts_with("+"));
        assert!(summary.contains("step 0"));
        assert!(!summary.contains(&format!("step {}", MAX_MILESTONES)));
        assert_eq!(
            trace.last_milestone(),
            format!("step {}", MAX_MILESTONES - 1)
        );
    }

    #[test]
    fn frontend_ready_is_reported_once() {
        let trace = StartupTrace::new();
        assert!(!trace.is_ready());
        assert!(trace.frontend_ready());
        assert!(!trace.frontend_ready());
        assert!(trace.is_ready());
    }

    #[test]
    fn first_ipc_milestones_are_recorded_once() {
        let trace = StartupTrace::new();
        trace.note_request("i18n.catalog");
        trace.note_request("settings.get");
        trace.note_response("i18n.catalog", true);
        trace.note_response("settings.get", true);
        let summary = trace.summary();
        assert_eq!(summary.matches("first IPC request received").count(), 1);
        assert_eq!(summary.matches("first IPC request answered").count(), 1);
    }

    #[test]
    fn setup_finished_is_recorded_as_a_milestone() {
        let trace = StartupTrace::new();
        assert!(!trace.is_setup_finished());
        trace.setup_finished();
        assert!(trace.is_setup_finished());
        assert_eq!(trace.last_milestone(), "setup finished");
    }

    #[test]
    fn a_hang_after_the_window_exists_is_still_setup_unfinished() {
        // The handle exists (window built) but setup never finished: the probe
        // must not run, because the stalled main thread would make it report
        // "UI thread blocked".
        let verdict = pick_verdict(false, Some(()), |_| {
            panic!("the main thread must not be probed while setup is unfinished")
        });
        assert_eq!(verdict, Verdict::SetupUnfinished);
    }

    #[test]
    fn no_window_handle_is_setup_unfinished() {
        let verdict = pick_verdict::<()>(false, None, |_| Verdict::FrontendMissing);
        assert_eq!(verdict, Verdict::SetupUnfinished);
        let verdict = pick_verdict::<()>(true, None, |_| Verdict::FrontendMissing);
        assert_eq!(verdict, Verdict::SetupUnfinished);
    }

    #[test]
    fn finished_setup_hands_the_verdict_to_the_main_thread_probe() {
        assert_eq!(
            pick_verdict(true, Some(()), |_| Verdict::MainThreadBlocked),
            Verdict::MainThreadBlocked
        );
        assert_eq!(
            pick_verdict(true, Some(()), |_| Verdict::FrontendMissing),
            Verdict::FrontendMissing
        );
    }

    #[test]
    fn verdicts_name_the_stuck_stage() {
        assert!(describe(&Verdict::SetupUnfinished, "window built").contains("window built"));
        assert!(describe(&Verdict::MainThreadBlocked, "x").contains("UI thread"));
        assert!(describe(&Verdict::FrontendMissing, "x").contains("never reported"));
    }
}
