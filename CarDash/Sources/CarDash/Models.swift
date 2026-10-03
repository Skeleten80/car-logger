import Foundation

// MARK: - API models
//
// These mirror the dash server's JSON contract exactly:
//
//   GET /api/info    -> {"session_id": int, "dbc_files": [str],
//                       "vehicle": str|null, "started_ts": float}
//   GET /api/latest  -> {"ts": float, "obd2": {...}, "signals": {...}}
//   GET /api/live    -> SSE, "data: <same JSON as /api/latest>" per event
//   GET /api/history?signal=<name>&limit=<n>
//                    -> {"signal": str, "samples": [[ts, value], ...]}
//
// OBD-II keys in /api/latest are only present once the logger has seen them,
// so every reading is optional here.

/// One OBD-II /latest payload.
struct LatestPayload: Decodable {
    var ts: Double
    var obd2: OBD2Readings
    var signals: [String: SignalReading]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ts = try c.decodeIfPresent(Double.self, forKey: .ts) ?? 0
        obd2 = try c.decodeIfPresent(OBD2Readings.self, forKey: .obd2) ?? OBD2Readings()
        signals = try c.decodeIfPresent([String: SignalReading].self, forKey: .signals) ?? [:]
    }

    private enum CodingKeys: String, CodingKey {
        case ts, obd2, signals
    }
}

/// Decoded OBD-II values. All optional: the server omits keys it has not
/// seen yet, and the dash must render "—" for those.
struct OBD2Readings: Decodable {
    var coolantTemp: Double?
    var rpm: Double?
    var speed: Double?
    var maf: Double?
    var throttle: Double?
    var fuelLevel: Double?

    init() {}

    private enum CodingKeys: String, CodingKey {
        case coolantTemp = "coolant_temp"
        case rpm, speed, maf, throttle
        case fuelLevel = "fuel_level"
    }
}

/// One DBC-decoded signal reading.
struct SignalReading: Decodable {
    var value: Double
    var unit: String
    var message: String
}

/// Logger session metadata. sessionID/startedTs are null when the DB has
/// no sessions yet (the dash was pointed at a fresh database).
struct SessionInfo: Decodable {
    var sessionID: Int?
    var dbcFiles: [String]
    var vehicle: String?
    var startedTs: Double?

    private enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case dbcFiles = "dbc_files"
        case vehicle
        case startedTs = "started_ts"
    }
}

/// Response from /api/history.
struct HistoryResponse: Decodable {
    var signal: String
    var samples: [[Double]]
}

// MARK: - Trip browser (/api/sessions, /api/trip)

/// One entry from GET /api/sessions (newest first). The per-table sample
/// counts ride along in the JSON but the app only needs identity here.
struct SessionSummary: Decodable, Identifiable {
    var id: Int
    var startedAt: Double
    var note: String

    private enum CodingKeys: String, CodingKey {
        case id, note
        case startedAt = "started_at"
    }
}

struct SessionsResponse: Decodable {
    var sessions: [SessionSummary]
}

/// One trouble code from the "dtcs" array of GET /api/trip.
struct TripDTC: Decodable, Identifiable {
    var id: String { code }
    var code: String
    var codeDescription: String
    var status: String

    private enum CodingKeys: String, CodingKey {
        case code, status
        case codeDescription = "description"
    }
}

/// Drive summary from GET /api/trip. Every metric is optional: a session
/// with no speed data simply has nil distance, and the UI renders "—".
/// The compiler synthesizes decodeIfPresent for these optionals, so both
/// missing keys and explicit nulls decode to nil.
struct TripSummary: Decodable {
    var sessionID: Int?
    var distanceKm: Double?
    var durationS: Double?
    var avgSpeedKmh: Double?
    var maxSpeedKmh: Double?
    var idlePct: Double?
    var fuelL: Double?
    var lPer100km: Double?
    var harshAccelEvents: Int?
    var harshBrakeEvents: Int?
    var visionInteresting: Int?
    var dtcCount: Int?
    var dtcs: [TripDTC]?

    private enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case distanceKm = "distance_km"
        case durationS = "duration_s"
        case avgSpeedKmh = "avg_speed_kmh"
        case maxSpeedKmh = "max_speed_kmh"
        case idlePct = "idle_pct"
        case fuelL = "fuel_l"
        case lPer100km = "l_per_100km"
        case harshAccelEvents = "harsh_accel_events"
        case harshBrakeEvents = "harsh_brake_events"
        case visionInteresting = "vision_interesting"
        case dtcCount = "dtc_count"
        case dtcs
    }
}
