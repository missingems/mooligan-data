import Foundation
import GeneratorSupport
import Testing

struct RetryingTests {
    @Test func whenTheConnectionTimesOut_shouldTryAgainAndReturnTheLaterAnswer() async throws {
        var calls = 0
        let answer = try await withRetries("meta", attempts: 3, delay: .milliseconds(1)) {
            calls += 1
            if calls < 3 { throw URLError(.timedOut) }
            return "ok"
        }
        #expect(answer == "ok")
        #expect(calls == 3)
    }

    @Test func whenEveryTryFails_shouldThrowTheLastFailureAfterTheLastTry() async {
        var calls = 0
        await #expect(throws: URLError.self) {
            try await withRetries("meta", attempts: 3, delay: .milliseconds(1)) {
                calls += 1
                throw URLError(.networkConnectionLost)
            }
        }
        #expect(calls == 3)
    }

    @Test func whenTheFailureIsNotTransient_shouldThrowAtOnce() async {
        var calls = 0
        await #expect(throws: DecodingError.self) {
            try await withRetries("meta", attempts: 3, delay: .milliseconds(1)) {
                calls += 1
                throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "not json"))
            }
        }
        #expect(calls == 1)
    }
}
