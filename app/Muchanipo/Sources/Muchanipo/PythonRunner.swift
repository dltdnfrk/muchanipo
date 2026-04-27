import Foundation

final class PythonRunner {
    enum RunnerError: Error {
        case alreadyRunning
        case processNotRunning
        case actionEncodingFailed
    }

    var onEvent: ((BackendEvent) -> Void)?
    var onOutputLine: ((String) -> Void)?
    var onTermination: ((Int32) -> Void)?

    private let executableURL: URL
    private let workingDirectoryURL: URL?
    private let encoder: JSONEncoder
    private var process: Process?
    private var stdinPipe: Pipe?
    private var eventTask: Task<Void, Never>?

    init(
        executableURL: URL = URL(fileURLWithPath: "/usr/bin/env"),
        workingDirectoryURL: URL? = nil,
        encoder: JSONEncoder = JSONEncoder()
    ) {
        self.executableURL = executableURL
        self.workingDirectoryURL = workingDirectoryURL
        self.encoder = encoder
    }

    var isRunning: Bool {
        process?.isRunning == true
    }

    @discardableResult
    func start(topic: String) throws -> EventStream {
        let stream = try startStream(topic: topic)
        eventTask = Task { [weak self] in
            do {
                for try await event in stream {
                    self?.onEvent?(event)
                    self?.onOutputLine?(event.displayLine)
                }
            } catch {
                self?.onOutputLine?("[error] event decode failed: \(error.localizedDescription)")
            }
        }
        return stream
    }

    func startStream(topic: String) throws -> EventStream {
        guard process == nil || process?.isRunning == false else {
            throw RunnerError.alreadyRunning
        }

        let process = Process()
        let stdoutPipe = Pipe()
        let stdinPipe = Pipe()

        process.executableURL = executableURL
        process.arguments = ["python3", "-m", "muchanipo", "serve", "--topic", topic]
        process.standardOutput = stdoutPipe
        process.standardInput = stdinPipe

        if let workingDirectoryURL {
            process.currentDirectoryURL = workingDirectoryURL
        }

        process.terminationHandler = { [weak self] _ in
            let exitCode = process.terminationStatus
            DispatchQueue.main.async {
                self?.onTermination?(exitCode)
                self?.eventTask = nil
                self?.process = nil
                self?.stdinPipe = nil
            }
        }

        try process.run()

        self.process = process
        self.stdinPipe = stdinPipe

        return EventStream(pipe: stdoutPipe)
    }

    func send(_ action: BackendAction) throws {
        guard let process, process.isRunning, let stdinPipe else {
            throw RunnerError.processNotRunning
        }

        var data = try encoder.encode(action)
        guard let newline = "\n".data(using: .utf8) else {
            throw RunnerError.actionEncodingFailed
        }

        data.append(newline)
        stdinPipe.fileHandleForWriting.write(data)
    }

    func stop() {
        guard let process else {
            return
        }

        if process.isRunning {
            process.terminate()
        }

        eventTask?.cancel()
        eventTask = nil
        self.process = nil
        self.stdinPipe = nil
    }
}

private extension BackendEvent {
    var displayLine: String {
        switch self {
        case .phaseChange(let phase, _):
            return "[phase] \(phase)"
        case .interviewQuestion(let question):
            return "[question] \(question.text)"
        case .councilRoundStart(let round, let layer):
            return "[round \(round)] start \(layer ?? "")"
        case .councilPersonaToken(let persona, let delta):
            return "[\(persona)] \(delta)"
        case .councilRoundDone(let round, let score):
            if let score {
                return "[round \(round)] done score=\(score)"
            }
            return "[round \(round)] done"
        case .reportChunk(let section, let markdown):
            return "[report \(section ?? "chunk")] \(markdown)"
        case .done(let reportPath):
            return "[done] \(reportPath ?? "")"
        case .error(let message):
            return "[error] \(message)"
        }
    }
}
