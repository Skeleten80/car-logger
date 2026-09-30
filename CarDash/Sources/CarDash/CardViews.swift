import SwiftUI

/// Small labeled telemetry readout card (MissionOps-style).
struct DashCard<Content: View>: View {
    var title: String
    var unit: String?
    var color: Color = .primary
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 4) {
                Text(title)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .tracking(1)
                if let unit {
                    Text(unit)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
            content()
                .foregroundStyle(color)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 8))
    }
}

/// Monospaced big-number readout with an em-dash placeholder when no data.
struct BigNumber: View {
    var value: Double?
    var format: String
    var font: Font = .system(.title, design: .monospaced)

    var body: some View {
        Text(value.map { String(format: format, $0) } ?? "—")
            .font(font)
            .lineLimit(1)
            .minimumScaleFactor(0.6)
    }
}

/// Section header for the dashboard.
struct DashSection: View {
    var title: String

    var body: some View {
        Text(title)
            .font(.caption)
            .foregroundStyle(.secondary)
            .tracking(1)
            .padding(.top, 4)
    }
}

/// Connection state pill: colored dot + label.
struct ConnectionPill: View {
    var state: CarDashViewModel.ConnectionState

    private var dot: Color {
        switch state {
        case .live: .green
        case .connecting, .reconnecting: .yellow
        case .offline: .red
        }
    }

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(dot)
                .frame(width: 8, height: 8)
            Text(state.label)
                .font(.caption)
                .bold()
                .tracking(1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(dot.opacity(0.15), in: Capsule())
        .foregroundStyle(dot)
    }
}
