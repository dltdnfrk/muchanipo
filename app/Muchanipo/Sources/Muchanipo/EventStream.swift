import Foundation

struct EventStream: AsyncSequence {
    typealias Element = BackendEvent

    private let fileHandle: FileHandle
    private let decoder: JSONDecoder

    init(fileHandle: FileHandle, decoder: JSONDecoder = JSONDecoder()) {
        self.fileHandle = fileHandle
        self.decoder = decoder
    }

    init(pipe: Pipe, decoder: JSONDecoder = JSONDecoder()) {
        self.init(fileHandle: pipe.fileHandleForReading, decoder: decoder)
    }

    func makeAsyncIterator() -> Iterator {
        Iterator(fileHandle: fileHandle, decoder: decoder)
    }
}

extension EventStream {
    struct Iterator: AsyncIteratorProtocol {
        private let fileHandle: FileHandle
        private let decoder: JSONDecoder
        private var buffer = Data()
        private var isEOF = false

        init(fileHandle: FileHandle, decoder: JSONDecoder) {
            self.fileHandle = fileHandle
            self.decoder = decoder
        }

        mutating func next() async throws -> BackendEvent? {
            while true {
                if let line = popLine() {
                    if line.isEmpty {
                        continue
                    }

                    return try decoder.decode(BackendEvent.self, from: line)
                }

                if isEOF {
                    guard !buffer.isEmpty else {
                        return nil
                    }

                    let line = buffer
                    buffer.removeAll()
                    return try decoder.decode(BackendEvent.self, from: line)
                }

                let chunk = await fileHandle.nextChunk()
                if chunk.isEmpty {
                    isEOF = true
                } else {
                    buffer.append(chunk)
                }
            }
        }

        private mutating func popLine() -> Data? {
            guard let newline = buffer.firstIndex(of: 0x0A) else {
                return nil
            }

            var line = buffer[..<newline]
            if line.last == 0x0D {
                line = line.dropLast()
            }

            buffer.removeSubrange(...newline)
            return Data(line)
        }
    }
}

private extension FileHandle {
    func nextChunk() async -> Data {
        await Task.detached(priority: .userInitiated) {
            self.readData(ofLength: 4096)
        }.value
    }
}
