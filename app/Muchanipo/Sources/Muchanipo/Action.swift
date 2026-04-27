import Foundation

enum BackendAction: Encodable, Equatable {
    case interviewAnswer(qID: String, answer: String)
    case approveDesignDoc
    case abort
}

extension BackendAction {
    private enum CodingKeys: String, CodingKey {
        case action
        case qID = "q_id"
        case answer
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)

        switch self {
        case .interviewAnswer(let qID, let answer):
            try container.encode("interview_answer", forKey: .action)
            try container.encode(qID, forKey: .qID)
            try container.encode(answer, forKey: .answer)
        case .approveDesignDoc:
            try container.encode("approve_designdoc", forKey: .action)
        case .abort:
            try container.encode("abort", forKey: .action)
        }
    }
}
