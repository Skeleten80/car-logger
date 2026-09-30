import Charts
import SwiftUI

/// The CarDash screen: header (title, vehicle, connection, host config),
/// gauge cards, an RPM strip chart, and the live decoded-signals table.
struct DashboardView: View {
    @StateObject private var vm = CarDashViewModel()

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    gaugeRow
                    HStack(alignment: .top, spacing: 12) {
                        rpmChart
                            .frame(minWidth: 320)
                        signalsTable
                            .frame(minWidth: 320)
                    }
                }
                .padding(12)
            }
        }
        .frame(minWidth: 1020, minHeight: 700)
        .preferredColorScheme(.dark)
        .onAppear { vm.connect() }
        .onDisappear { vm.disconnect() }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: 14) {
            Text("CAR DASH")
                .font(.headline)
                .tracking(3)
            if let vehicle = vm.info?.vehicle, !vehicle.isEmpty {
                Text(vehicle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            } else if let sid = vm.info?.sessionID {
                Text("SESSION #\(sid)")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            ConnectionPill(state: vm.state)
            if let err = vm.lastError, vm.state != .live {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .lineLimit(1)
            }
            Spacer()
            TextField("http://127.0.0.1:8080", text: $vm.baseURLString)
                .textFieldStyle(.roundedBorder)
                .frame(width: 220)
                .font(.system(.body, design: .monospaced))
                .disabled(vm.isConnected)
            Button(vm.isConnected ? "Disconnect" : "Connect") {
                vm.isConnected ? vm.disconnect() : vm.connect()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.small)
        }
    }

    // MARK: - Gauge cards

    private var gaugeRow: some View {
        HStack(spacing: 10) {
            // RPM arc gauge, 0–8000.
            DashCard(title: "ENGINE SPEED", unit: "rpm") {
                Gauge(value: vm.obd2.rpm ?? 0, in: 0...8000) {
                    Text("RPM")
                } currentValueLabel: {
                    Text(vm.obd2.rpm.map { "\(Int($0))" } ?? "—")
                        .font(.system(.title2, design: .monospaced))
                }
                .gaugeStyle(.accessoryCircular)
                .tint(Gradient(colors: [.green, .yellow, .red]))
                .frame(height: 90)
            }

            // Speed, big number.
            DashCard(title: "SPEED", unit: "km/h") {
                BigNumber(value: vm.obd2.speed, format: "%.0f")
                    .frame(maxHeight: .infinity, alignment: .center)
            }

            // Coolant temperature bar.
            DashCard(title: "COOLANT", unit: "degC") {
                VStack(alignment: .leading, spacing: 6) {
                    BigNumber(value: vm.obd2.coolantTemp, format: "%.0f",
                              font: .system(.title2, design: .monospaced))
                    Gauge(value: vm.obd2.coolantTemp ?? -40, in: -40...130) {}
                        .gaugeStyle(.accessoryLinearCapacity)
                        .tint((vm.obd2.coolantTemp ?? 0) > 105 ? .red : .cyan)
                }
            }

            // Throttle.
            DashCard(title: "THROTTLE", unit: "%") {
                BigNumber(value: vm.obd2.throttle, format: "%.0f")
                    .frame(maxHeight: .infinity, alignment: .center)
            }

            // Fuel level.
            DashCard(title: "FUEL", unit: "%") {
                VStack(alignment: .leading, spacing: 6) {
                    BigNumber(value: vm.obd2.fuelLevel, format: "%.0f",
                              font: .system(.title2, design: .monospaced))
                    Gauge(value: vm.obd2.fuelLevel ?? 0, in: 0...100) {}
                        .gaugeStyle(.accessoryLinearCapacity)
                        .tint((vm.obd2.fuelLevel ?? 100) < 15 ? .red : .green)
                }
            }

            // MAF.
            DashCard(title: "MAF", unit: "g/s") {
                BigNumber(value: vm.obd2.maf, format: "%.1f")
                    .frame(maxHeight: .infinity, alignment: .center)
            }
        }
    }

    // MARK: - RPM strip chart

    private var rpmYMax: Double {
        max(1000, (vm.rpmHistory.map(\.v).max() ?? 0) * 1.1)
    }

    private var rpmChart: some View {
        VStack(alignment: .leading, spacing: 4) {
            DashSection(title: "ENGINE SPEED HISTORY — RPM")
            Chart(vm.rpmHistory) { p in
                LineMark(x: .value("t", p.t), y: .value("rpm", p.v))
                    .foregroundStyle(.green)
            }
            .chartYScale(domain: 0...rpmYMax)
            .chartXAxisLabel("time")
            .frame(height: 220)
            .padding(10)
            .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 8))
        }
    }

    // MARK: - Decoded signals table

    private var signalsTable: some View {
        VStack(alignment: .leading, spacing: 4) {
            DashSection(title: "DECODED SIGNALS — DBC")
            if vm.signalNames.isEmpty {
                Text("No DBC loaded — raw OBD-II only")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
                    .padding(10)
                    .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 8))
                    .frame(height: 220)
            } else {
                List {
                    ForEach(vm.signalNames, id: \.self) { name in
                        if let s = vm.signals[name] {
                            HStack {
                                Text(name)
                                    .font(.system(.body, design: .monospaced))
                                Spacer()
                                Text(String(format: "%.3g", s.value))
                                    .font(.system(.body, design: .monospaced))
                                Text(s.unit)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                    .frame(width: 52, alignment: .leading)
                                Text(s.message)
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                                    .frame(width: 90, alignment: .leading)
                                    .lineLimit(1)
                            }
                        }
                    }
                }
                .frame(height: 220)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
    }
}
