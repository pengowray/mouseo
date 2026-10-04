//! Prints one JSON line each time the focused COSMIC window changes, moves or resizes:
//! {"app_id": "firefox", "x": 10, "y": 20, "width": 800, "height": 450}
//! x and y are relative to the window's output. Prints {} when no window is focused.
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
    last: String,
}

impl AppData {
    fn focused_json(&self) -> String {
        for info in self.toplevel_info_state.toplevels() {
            if !info.state.contains(&State::Activated) {
                continue;
            }
            let app_id = info.app_id.replace('\\', "\\\\").replace('"', "\\\"");
            return match info.geometry.values().next() {
                Some(g) => format!(
                    r#"{{"app_id": "{app_id}", "x": {}, "y": {}, "width": {}, "height": {}}}"#,
                    g.x, g.y, g.width, g.height
                ),
                None => format!(r#"{{"app_id": "{app_id}"}}"#),
            };
        }
        "{}".to_string()
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
        let json = self.focused_json();
        if json != self.last {
            let mut out = std::io::stdout().lock();
            if writeln!(out, "{json}").and_then(|_| out.flush()).is_err() {
                std::process::exit(0); // reader went away
            }
            self.last = json;
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
        last: String::new(),
    };
    loop {
        event_queue.blocking_dispatch(&mut app_data).expect("Wayland connection lost");
    }
}

sctk::delegate_output!(AppData);
sctk::delegate_registry!(AppData);
cosmic_client_toolkit::delegate_toplevel_info!(AppData);
