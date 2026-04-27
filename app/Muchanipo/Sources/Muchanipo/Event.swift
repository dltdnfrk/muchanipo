import Foundation

enum BackendEvent: Decodable, Equatable {
    case phaseChange(phase: String, data: JSONValue?)
    case interviewQuestion(InterviewQuestion)
    case councilRoundStart(round: Int, layer: String?)
    case councilPersonaToken(persona: String, delta: String)
    case councilRoundDone(round: Int, score: Int?)
    case reportChunk(section: String?, markdown: String)
    case done(reportPath: String?)
    case error(message: String)
}

struct InterviewQuestion: Decodable, Equatable {
    let qID: String
    let text: String
    let options: [InterviewOption]

    private enum CodingKeys: String, CodingKey {
        case qID = "q_id"
        case text
        case options
    }
}

struct InterviewOption: Decodable, Equatable {
    let id: String?
    let label: String?
    let text: String?
    let value: String?
}

enum JSONValue: Decodable, Equatable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()

        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }
}

extension BackendEvent {
    private enum CodingKeys: String, CodingKey {
        case event
        case phase
        case data
        case round
        case layer
        case persona
        case delta
        case score
        case section
        case markdown
        case reportPath = "report_path"
        case message
    }

    private enum EventName: String, Decodable {
        case phaseChange = "phase_change"
        case interviewQuestion = "interview_question"
        case councilRoundStart = "council_round_start"
        case councilPersonaToken = "council_persona_token"
        case councilRoundDone = "council_round_done"
        case reportChunk = "report_chunk"
        case done
        case error
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let eventName = try container.decode(EventName.self, forKey: .event)

        switch eventName {
        case .phaseChange:
            self = .phaseChange(
                phase: try container.decode(String.self, forKey: .phase),
                data: try container.decodeIfPresent(JSONValue.self, forKey: .data)
            )
        case .interviewQuestion:
            self = .interviewQuestion(try container.decode(InterviewQuestion.self, forKey: .data))
        case .councilRoundStart:
            self = .councilRoundStart(
                round: try container.decode(Int.self, forKey: .round),
                layer: try container.decodeIfPresent(String.self, forKey: .layer)
            )
        case .councilPersonaToken:
            self = .councilPersonaToken(
                persona: try container.decode(String.self, forKey: .persona),
                delta: try container.decode(String.self, forKey: .delta)
            )
        case .councilRoundDone:
            self = .councilRoundDone(
                round: try container.decode(Int.self, forKey: .round),
                score: try container.decodeIfPresent(Int.self, forKey: .score)
            )
        case .reportChunk:
            self = .reportChunk(
                section: try container.decodeIfPresent(String.self, forKey: .section),
                markdown: try container.decode(String.self, forKey: .markdown)
            )
        case .done:
            self = .done(reportPath: try container.decodeIfPresent(String.self, forKey: .reportPath))
        case .error:
            self = .error(message: try container.decode(String.self, forKey: .message))
        }
    }
}
