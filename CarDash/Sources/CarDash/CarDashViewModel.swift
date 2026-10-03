import Combine
import Foundation

/// Drives the dash: fetches /api/info, consumes the /api/live SSE stream,
/// backfills RPM history from /api/history, and publishes everything the
/// dashboard needs. Reconnects with exponential backoff when the stream
/// drops; connection state is published for the header pill.
@MainActor
final class CarDashViewModel: ObservableObject {
    struct PlotPoint: Identifiable {
        let id: Int
        let t: Double
        let v: Double
    }

    enum ConnectionState {
        case offline, connecting, live, reconnecting

        var label: String {
            switch self {
            case .offline: "OFFLINE"
            case .connecting: "CONNECTING"
            case .live: "LIVE"
            case .reconnecting: "RECONNECTING"
            }
        }
    }

    // MARK: - Published state

    @Published var baseURLString: String
    @Published private(set) var state: ConnectionState = .offline
    @Published private(set) var info: SessionInfo?
    @Published private(set) var lastTs: Double?
    @Published private(set) var obd2 = OBD2Readings()
    @Published private(set) var signals: [String: SignalReading] = [:]
    @Published private(set) var rpmHistory: [PlotPoint] = []
    @Published private(set) var lastError: String?
    @Published private(set) var sessions: [SessionSummary] = []
    @Published private(set) var trip: TripSummary?
    @Published var selectedSessionID: Int? {
        didSet {
            guard oldValue != selectedSessionID else { return }
            Task { [weak self] in await self?.fetchTrip() }
        }
    }

    // MARK: - Config

    private static let baseURLKey = "CarDash.baseURL"
    private static let defaultBaseURL = "http://127.0.0.1:8080"
    private let historyCap = 2400  // ~20 min at 2 Hz

    private var streamTask: Task<Void, Never>?
    private var pointID = 0
    private var hasEverConnected = false

    var isConnected: Bool {
        state == .live || state == .connecting || state == .reconnecting
    }

    var baseURL: URL? {
        URL(string: baseURLString.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    var signalNames: [String] { signals.keys.sorted() }

    init() {
        baseURLString = UserDefaults.standard.string(forKey: Self.baseURLKey)
            ?? Self.defaultBaseURL
    }

    // MARK: - Connect / disconnect

    func connect() {
        UserDefaults.standard.set(baseURLString, forKey: Self.baseURLKey)
        disconnect()
        lastError = nil
        state = .connecting
        streamTask = Task.detached { [weak self] in
            await self?.runStream()
        }
        Task { [weak self] in
            await self?.fetchInfo()
            await self?.backfillRPMHistory()
            await self?.fetchSessions()
            await self?.fetchTrip()
        }
    }

    func disconnect() {
        streamTask?.cancel()
        streamTask = nil
        state = .offline
    }

    // MARK: - REST calls

    private func api(_ path: String, query: [URLQueryItem] = []) async throws -> Data {
        guard let base = baseURL else { throw URLError(.badURL) }
        var comps = URLComponents(url: base.appendingPathComponent(path),
                                  resolvingAgainstBaseURL: false)
        if !query.isEmpty { comps?.queryItems = query }
        guard let url = comps?.url else { throw URLError(.badURL) }
        var req = URLRequest(url: url)
        req.timeoutInterval = 15
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        return data
    }

    private func fetchInfo() async {
        do {
            let data = try await api("api/info")
            let info = try JSONDecoder().decode(SessionInfo.self, from: data)
            self.info = info
        } catch {
            lastError = "info: \(error.localizedDescription)"
        }
    }

    private func backfillRPMHistory() async {
        do {
            let data = try await api("api/history",
                                     query: [URLQueryItem(name: "signal", value: "rpm"),
                                             URLQueryItem(name: "limit", value: "600")])
            let resp = try JSONDecoder().decode(HistoryResponse.self, from: data)
            let pts = resp.samples.compactMap { s -> PlotPoint? in
                guard s.count == 2 else { return nil }
                pointID += 1
                return PlotPoint(id: pointID, t: s[0], v: s[1])
            }
            rpmHistory = pts
        } catch {
            // Backfill is best-effort; live SSE points still accumulate.
        }
    }

    // MARK: - Trip browser

    private func fetchSessions() async {
        do {
            let data = try await api("api/sessions")
            let resp = try JSONDecoder().decode(SessionsResponse.self,
                                                from: data)
            sessions = resp.sessions
            if selectedSessionID == nil {
                selectedSessionID = resp.sessions.first?.id
            }
        } catch {
            // Best-effort: the live dash works without the trip browser.
        }
    }

    private func fetchTrip() async {
        guard let sid = selectedSessionID else {
            trip = nil
            return
        }
        do {
            let data = try await api(
                "api/trip",
                query: [URLQueryItem(name: "session_id",
                                     value: String(sid))])
            trip = try JSONDecoder().decode(TripSummary.self, from: data)
        } catch {
            trip = nil
        }
    }

    // MARK: - SSE stream

    /// Runs on a detached task (off the main actor); all state updates hop
    /// back to the main actor. Reconnects with exponential backoff until
    /// cancelled.
    private nonisolated func runStream() async {
        var backoff = 1.0
        while !Task.isCancelled {
            let firstAttempt = await MainActor.run { !self.hasEverConnected }
            await MainActor.run {
                self.state = firstAttempt ? .connecting : .reconnecting
            }
            do {
                try await self.streamOnce()
                backoff = 1.0
                // Clean EOF from the server: loop straight back in.
            } catch is CancellationError {
                break
            } catch {
                await MainActor.run {
                    self.lastError = error.localizedDescription
                    self.state = self.hasEverConnected ? .reconnecting : .offline
                }
                try? await Task.sleep(nanoseconds: UInt64(backoff * 1_000_000_000))
                backoff = min(backoff * 2, 30)
            }
        }
    }

    /// Opens one /api/live stream and pumps events until it ends or errors.
    private nonisolated func streamOnce() async throws {
        guard let base = await MainActor.run(body: { self.baseURL }) else {
            throw URLError(.badURL)
        }
        var req = URLRequest(url: base.appendingPathComponent("api/live"))
        req.timeoutInterval = 60
        let (bytes, resp) = try await URLSession.shared.bytes(for: req)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else {
            throw URLError(.badServerResponse)
        }
        var firstEvent = true
        for try await line in bytes.lines {
            try Task.checkCancellation()
            guard line.hasPrefix("data:") else { continue }
            let json = line.dropFirst("data:".count)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard !json.isEmpty, let data = json.data(using: .utf8) else { continue }
            do {
                let payload = try JSONDecoder().decode(LatestPayload.self, from: data)
                if firstEvent {
                    firstEvent = false
                    await MainActor.run {
                        self.hasEverConnected = true
                        self.state = .live
                    }
                }
                await MainActor.run { self.apply(payload) }
            } catch {
                // Skip malformed events; keep the stream alive.
                continue
            }
        }
    }

    // MARK: - Apply

    private func apply(_ payload: LatestPayload) {
        lastTs = payload.ts
        if let v = payload.obd2.coolantTemp { obd2.coolantTemp = v }
        if let v = payload.obd2.rpm {
            obd2.rpm = v
            pointID += 1
            rpmHistory.append(PlotPoint(id: pointID, t: payload.ts, v: v))
            if rpmHistory.count > historyCap {
                rpmHistory.removeFirst(historyCap / 2)
            }
        }
        if let v = payload.obd2.speed { obd2.speed = v }
        if let v = payload.obd2.maf { obd2.maf = v }
        if let v = payload.obd2.throttle { obd2.throttle = v }
        if let v = payload.obd2.fuelLevel { obd2.fuelLevel = v }
        signals = payload.signals
    }
}
