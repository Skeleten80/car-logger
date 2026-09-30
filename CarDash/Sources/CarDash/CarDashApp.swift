import SwiftUI

/// CarDash entry point: the live dashboard client for the car-logger
/// dash server (phase 2 of the vehicle-computer project).
@main
struct CarDashApp: App {
    var body: some Scene {
        WindowGroup {
            DashboardView()
        }
        .windowStyle(.automatic)
        .commands {
            // Keep the standard app menu; nothing custom needed.
        }
    }
}
