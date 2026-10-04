//! Prints one JSON line for each COSMIC window that appears, changes, moves or resizes:
//! {"id": "...", "app_id": "firefox", "focused": true, "x": 10, "y": 20, "width": 800, "height": 450}
//! x and y are relative to the window's output. A closed window prints {"id": "...", "closed": true}.
//! naga-daemon reads this to resize windows proportionally.

use cosmic_client_toolkit::cosmic_protocols::toplevel_info::v1::client::zcosmic_toplevel_handle_v1::State;
use cosmic_client_toolkit::toplevel_info::{ToplevelInfoHandler, ToplevelInfoState};
use sctk::{
    output::{OutputHandler, OutputState},
    registry::{ProvidesRegistryState, RegistryState},
};
use std::io::Write;
use wayland_client::{Connection, QueueHandle, globals::registry_queue_init, protocol::wl_output};
use wayland_protocols::ext::foreign_toplevel_list::v1::client::ext_foreign_toplevel_handle_v1::ExtForeignToplevelHandleV1;

struct AppData {
    output_state: OutputState,
    registry_state: RegistryState,
    toplevel_info_state: ToplevelInfoState,
    last: std::collections::HashMap<String, String>,
}

fn json_str(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"")
}

impl AppData {
    fn window_json(info: &cosmic_client_toolkit::toplevel_info::ToplevelInfo) -> String {
        let id = json_str(&info.identifier);
        let app_id = json_str(&info.app_id);
        let focused = info.state.contains(&State::Activated);
        let geometry = match info.geometry.values().next() {
            Some(g) => format!(r#", "x": {}, "y": {}, "width": {}, "height": {}"#, g.x, g.y, g.width, g.height),
            None => String::new(),
        };
        format!(r#"{{"id": "{id}", "app_id": "{app_id}", "focused": {focused}{geometry}}}"#)
    }
}

impl ProvidesRegistryState for AppData {
    fn registry(&mut self) -> &mut RegistryState {
        &mut self.registry_state
    }
    sctk::registry_handlers!(OutputState);
}

// Outputs must be bound for toplevels to report their geometry
impl OutputHandler for AppData {
    fn output_state(&mut self) -> &mut OutputState {
        &mut self.output_state
    }
    fn new_output(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {}
    fn update_output(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {}
    fn output_destroyed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {}
}

impl ToplevelInfoHandler for AppData {
    fn toplevel_info_state(&mut self) -> &mut ToplevelInfoState {
        &mut self.toplevel_info_state
    }
    fn new_toplevel(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &ExtForeignToplevelHandleV1) {}
    fn update_toplevel(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &ExtForeignToplevelHandleV1) {}
    fn toplevel_closed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &ExtForeignToplevelHandleV1) {}

    fn info_done(&mut self, _: &Connection, _: &QueueHandle<Self>) {
        let mut lines = Vec::new();
        let mut seen = std::collections::HashSet::new();
        for info in self.toplevel_info_state.toplevels() {
            seen.insert(info.identifier.clone());
            let json = Self::window_json(info);
            if self.last.get(&info.identifier) != Some(&json) {
                self.last.insert(info.identifier.clone(), json.clone());
                lines.push(json);
            }
        }
        self.last.retain(|id, _| {
            let open = seen.contains(id);
            if !open {
                lines.push(format!(r#"{{"id": "{}", "closed": true}}"#, json_str(id)));
            }
            open
        });
        if lines.is_empty() {
            return;
        }
        let mut out = std::io::stdout().lock();
        let text = lines.join("\n") + "\n";
        if out.write_all(text.as_bytes()).and_then(|_| out.flush()).is_err() {
            std::process::exit(0); // reader went away
        }
    }
}

fn main() {
    let conn = Connection::connect_to_env().expect("cannot connect to the Wayland display");
    let (globals, mut event_queue) = registry_queue_init(&conn).expect("cannot read Wayland globals");
    let qh = event_queue.handle();
    let registry_state = RegistryState::new(&globals);
    let mut app_data = AppData {
        output_state: OutputState::new(&globals, &qh),
        toplevel_info_state: ToplevelInfoState::new(&registry_state, &qh),
        registry_state,
        last: std::collections::HashMap::new(),
    };
    loop {
        event_queue.blocking_dispatch(&mut app_data).expect("Wayland connection lost");
    }
}

sctk::delegate_output!(AppData);
sctk::delegate_registry!(AppData);
cosmic_client_toolkit::delegate_toplevel_info!(AppData);
