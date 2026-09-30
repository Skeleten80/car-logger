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
