import Foundation

/// Runs `body` again after a transient failure, up to `attempts` times in all, waiting `delay`
/// between tries. MTGJSON answers slowly now and then, and one timed-out `Meta.json` failed a
/// whole catalog build.
public func withRetries<T>(
    _ what: String,
    attempts: Int = 3,
    delay: Duration = .seconds(15),
    _ body: () async throws -> T
) async throws -> T {
    var attempt = 1
    while true {
        do {
            return try await body()
        } catch where attempt < attempts && isTransient(error) {
            print("⚠️ \(what) failed (attempt \(attempt) of \(attempts)): \(error.localizedDescription); trying again in \(delay)")
            attempt += 1
            try await Task.sleep(for: delay)
        }
    }
}

/// A failure a second try tends to fix: the connection timed out, dropped, or could not be made.
/// Anything else — a bad decode, a file that cannot be written — is thrown at once.
public func isTransient(_ error: any Error) -> Bool {
    guard let urlError = error as? URLError else { return false }
    switch urlError.code {
    case .timedOut, .networkConnectionLost, .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed,
         .notConnectedToInternet, .resourceUnavailable, .badServerResponse, .secureConnectionFailed:
        return true
    default:
        return false
    }
}
