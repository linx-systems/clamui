use clamui_core::common::Event;
use serde_json::Value;
use std::{
    collections::{hash_map::Entry, HashMap},
    time::{Duration, Instant},
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct Registration(u64);

pub(crate) struct ScanProgressCoalescer {
    interval: Duration,
    next_registration: u64,
    operations: HashMap<String, ProgressState>,
}

struct ProgressState {
    registration: Registration,
    last_forwarded: Option<Instant>,
    pending: Option<Event>,
}

impl ScanProgressCoalescer {
    pub(crate) fn new(interval: Duration) -> Self {
        Self {
            interval,
            next_registration: 1,
            operations: HashMap::new(),
        }
    }

    pub(crate) fn register(&mut self, operation_id: &str) -> Option<Registration> {
        match self.operations.entry(operation_id.to_owned()) {
            Entry::Vacant(entry) => {
                let registration = Registration(self.next_registration);
                self.next_registration = self.next_registration.checked_add(1)?;
                entry.insert(ProgressState {
                    registration,
                    last_forwarded: None,
                    pending: None,
                });
                Some(registration)
            }
            Entry::Occupied(_) => None,
        }
    }

    pub(crate) fn forward(&mut self, event: Event, now: Instant, mut emit: impl FnMut(Event)) {
        if event.event == "scan-complete" {
            if let Some(pending) = event
                .data
                .get("id")
                .and_then(Value::as_str)
                .and_then(|operation_id| self.operations.remove(operation_id))
                .and_then(|state| state.pending)
            {
                emit(pending);
            }
            emit(event);
            return;
        }

        if event.event != "scan-progress" {
            emit(event);
            return;
        }

        let Some(operation_id) = event.data.get("id").and_then(Value::as_str) else {
            emit(event);
            return;
        };
        let Some(state) = self.operations.get_mut(operation_id) else {
            emit(event);
            return;
        };

        if !has_empty_threat_delta(&event) {
            state.pending = None;
            state.last_forwarded = Some(now);
            emit(event);
            return;
        }

        let is_due = match state.last_forwarded {
            Some(last_forwarded) => now.saturating_duration_since(last_forwarded) >= self.interval,
            None => true,
        };
        if is_due {
            state.pending = None;
            state.last_forwarded = Some(now);
            emit(event);
        } else {
            state.pending = Some(event);
        }
    }

    pub(crate) fn finish(
        &mut self,
        operation_id: &str,
        registration: Registration,
        mut emit: impl FnMut(Event),
    ) {
        let is_current = self
            .operations
            .get(operation_id)
            .is_some_and(|state| state.registration == registration);
        if !is_current {
            return;
        }

        if let Some(pending) = self
            .operations
            .remove(operation_id)
            .and_then(|state| state.pending)
        {
            emit(pending);
        }
    }
}

fn has_empty_threat_delta(event: &Event) -> bool {
    event
        .data
        .get("new_threats")
        .and_then(Value::as_array)
        .is_some_and(|threats| threats.is_empty())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn progress(id: &str, files_scanned: u64, threats: &[&str]) -> Event {
        Event {
            event: "scan-progress".into(),
            data: json!({
                "id": id,
                "files_scanned": files_scanned,
                "infected_count": threats.len(),
                "new_threats": threats.iter().map(|name| json!({"threat_name": name})).collect::<Vec<_>>(),
            }),
        }
    }

    fn complete(id: &str) -> Event {
        Event {
            event: "scan-complete".into(),
            data: json!({"id": id, "result": {"status": "clean"}}),
        }
    }

    fn progress_counts(events: &[Event]) -> Vec<u64> {
        events
            .iter()
            .filter(|event| event.event == "scan-progress")
            .map(|event| event.data["files_scanned"].as_u64().unwrap())
            .collect()
    }

    #[test]
    fn forwards_latest_snapshot_at_the_interval_boundary() {
        let start = Instant::now();
        let mut coalescer = ScanProgressCoalescer::new(Duration::from_millis(50));
        let mut emitted = Vec::new();
        let registration = coalescer.register("scan").unwrap();

        coalescer.forward(progress("scan", 1, &[]), start, |event| emitted.push(event));
        coalescer.forward(
            progress("scan", 2, &[]),
            start + Duration::from_millis(49),
            |event| emitted.push(event),
        );
        coalescer.forward(
            progress("scan", 3, &[]),
            start + Duration::from_millis(50),
            |event| emitted.push(event),
        );
        coalescer.finish("scan", registration, |event| emitted.push(event));

        assert_eq!(progress_counts(&emitted), vec![1, 3]);
    }

    #[test]
    fn completion_flushes_latest_snapshot_before_terminal_event_and_removes_state() {
        let start = Instant::now();
        let mut coalescer = ScanProgressCoalescer::new(Duration::from_millis(50));
        let mut emitted = Vec::new();
        let registration = coalescer.register("scan").unwrap();

        coalescer.forward(progress("scan", 1, &[]), start, |event| emitted.push(event));
        coalescer.forward(
            progress("scan", 3, &[]),
            start + Duration::from_millis(20),
            |event| emitted.push(event),
        );
        coalescer.forward(
            complete("scan"),
            start + Duration::from_millis(21),
            |event| emitted.push(event),
        );
        coalescer.finish("scan", registration, |event| emitted.push(event));

        assert_eq!(
            emitted
                .iter()
                .map(|event| event.event.as_str())
                .collect::<Vec<_>>(),
            vec!["scan-progress", "scan-progress", "scan-complete"]
        );
        assert_eq!(progress_counts(&emitted), vec![1, 3]);
    }

    #[test]
    fn threat_deltas_are_not_lost_while_ordinary_snapshots_are_replaced() {
        let start = Instant::now();
        let mut coalescer = ScanProgressCoalescer::new(Duration::from_millis(50));
        let mut emitted = Vec::new();
        let registration = coalescer.register("scan").unwrap();

        coalescer.forward(progress("scan", 1, &[]), start, |event| emitted.push(event));
        coalescer.forward(
            progress("scan", 2, &[]),
            start + Duration::from_millis(1),
            |event| emitted.push(event),
        );
        coalescer.forward(
            progress("scan", 3, &["threat-a"]),
            start + Duration::from_millis(2),
            |event| emitted.push(event),
        );
        coalescer.forward(
            progress("scan", 4, &[]),
            start + Duration::from_millis(3),
            |event| emitted.push(event),
        );
        coalescer.forward(
            progress("scan", 5, &["threat-b"]),
            start + Duration::from_millis(4),
            |event| emitted.push(event),
        );
        coalescer.finish("scan", registration, |event| emitted.push(event));

        assert_eq!(progress_counts(&emitted), vec![1, 3, 5]);
        assert_eq!(
            emitted
                .iter()
                .filter(|event| event.event == "scan-progress")
                .flat_map(|event| event.data["new_threats"].as_array().unwrap())
                .filter_map(|threat| threat["threat_name"].as_str())
                .collect::<Vec<_>>(),
            vec!["threat-a", "threat-b"]
        );
    }

    #[test]
    fn keeps_interleaved_operations_independent() {
        let start = Instant::now();
        let mut coalescer = ScanProgressCoalescer::new(Duration::from_millis(50));
        let mut emitted = Vec::new();
        let a_registration = coalescer.register("a").unwrap();
        let b_registration = coalescer.register("b").unwrap();

        coalescer.forward(progress("a", 1, &[]), start, |event| emitted.push(event));
        coalescer.forward(
            progress("b", 1, &[]),
            start + Duration::from_millis(1),
            |event| emitted.push(event),
        );
        coalescer.forward(
            progress("a", 2, &[]),
            start + Duration::from_millis(2),
            |event| emitted.push(event),
        );
        coalescer.forward(
            progress("b", 2, &[]),
            start + Duration::from_millis(3),
            |event| emitted.push(event),
        );
        coalescer.forward(
            progress("a", 3, &[]),
            start + Duration::from_millis(50),
            |event| emitted.push(event),
        );
        coalescer.finish("b", b_registration, |event| emitted.push(event));
        coalescer.finish("a", a_registration, |event| emitted.push(event));

        assert_eq!(
            emitted
                .iter()
                .filter(|event| event.event == "scan-progress")
                .map(|event| (
                    event.data["id"].as_str().unwrap(),
                    event.data["files_scanned"].as_u64().unwrap()
                ))
                .collect::<Vec<_>>(),
            vec![("a", 1), ("b", 1), ("a", 3), ("b", 2)]
        );
    }

    #[test]
    fn stale_finish_does_not_remove_a_reused_operation_id() {
        let start = Instant::now();
        let mut coalescer = ScanProgressCoalescer::new(Duration::from_millis(50));
        let mut emitted = Vec::new();
        let first_registration = coalescer.register("scan").unwrap();
        assert!(coalescer.register("scan").is_none());

        coalescer.forward(progress("scan", 1, &[]), start, |event| emitted.push(event));
        coalescer.forward(
            progress("scan", 2, &[]),
            start + Duration::from_millis(1),
            |event| emitted.push(event),
        );
        coalescer.forward(
            complete("scan"),
            start + Duration::from_millis(2),
            |event| emitted.push(event),
        );

        let second_registration = coalescer.register("scan").unwrap();
        assert_ne!(first_registration, second_registration);
        coalescer.forward(
            progress("scan", 10, &[]),
            start + Duration::from_millis(3),
            |event| emitted.push(event),
        );
        coalescer.forward(
            progress("scan", 11, &[]),
            start + Duration::from_millis(4),
            |event| emitted.push(event),
        );
        coalescer.finish("scan", first_registration, |event| emitted.push(event));
        coalescer.finish("scan", second_registration, |event| emitted.push(event));

        assert_eq!(
            emitted
                .iter()
                .map(|event| event.event.as_str())
                .collect::<Vec<_>>(),
            vec![
                "scan-progress",
                "scan-progress",
                "scan-complete",
                "scan-progress",
                "scan-progress",
            ]
        );
        assert_eq!(progress_counts(&emitted), vec![1, 2, 10, 11]);
    }
}
