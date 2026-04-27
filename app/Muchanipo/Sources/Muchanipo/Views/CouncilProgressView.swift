import AppKit

final class CouncilProgressView: NSView {
    private final class RoundRow {
        let container = NSStackView()
        let titleLabel = NSTextField(labelWithString: "")
        let detailLabel = NSTextField(wrappingLabelWithString: "")
        let statusLabel = NSTextField(labelWithString: "Running")

        init(round: Int, layer: String) {
            container.orientation = .vertical
            container.alignment = .leading
            container.spacing = 4

            titleLabel.font = .boldSystemFont(ofSize: 13)
            titleLabel.stringValue = "Round \(round) - \(layer)"

            detailLabel.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
            detailLabel.textColor = .secondaryLabelColor
            detailLabel.maximumNumberOfLines = 4

            statusLabel.font = .systemFont(ofSize: 12)
            statusLabel.textColor = .controlAccentColor

            container.addArrangedSubview(titleLabel)
            container.addArrangedSubview(detailLabel)
            container.addArrangedSubview(statusLabel)
        }
    }

    private let scrollView = NSScrollView()
    private let stackView = NSStackView()
    private var rowsByRound: [Int: RoundRow] = [:]
    private var currentRound: Int?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        configureLayout()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        configureLayout()
    }

    func reset() {
        rowsByRound.removeAll()
        currentRound = nil
        stackView.arrangedSubviews.forEach { view in
            stackView.removeArrangedSubview(view)
            view.removeFromSuperview()
        }
    }

    func startRound(_ round: Int, layer: String) {
        currentRound = round
        let row = RoundRow(round: round, layer: layer)
        rowsByRound[round] = row
        stackView.addArrangedSubview(row.container)
        isHidden = false
    }

    func appendPersonaToken(round: Int, persona: String, delta: String) {
        let row = rowForRound(round)
        let current = row.detailLabel.stringValue
        let prefix = current.isEmpty ? "" : "\n"
        row.detailLabel.stringValue = "\(current)\(prefix)\(persona): \(delta)"
    }

    func finishRound(_ round: Int, score: Int?) {
        let row = rowForRound(round)
        if let score {
            row.statusLabel.stringValue = "Done - score \(score)"
        } else {
            row.statusLabel.stringValue = "Done"
        }
        row.statusLabel.textColor = .systemGreen
    }

    func appendStatus(_ text: String) {
        let row = RoundRow(round: rowsByRound.count + 1, layer: "Status")
        row.detailLabel.stringValue = text
        row.statusLabel.stringValue = "Updated"
        rowsByRound[rowsByRound.count + 1] = row
        stackView.addArrangedSubview(row.container)
        isHidden = false
    }

    func apply(_ event: BackendEvent) {
        switch event {
        case .phaseChange(let phase, _):
            appendStatus("Phase: \(phase)")
        case .councilRoundStart(let round, let layer):
            startRound(round, layer: layer ?? "Council")
        case .councilPersonaToken(let persona, let delta):
            appendPersonaToken(round: currentRound ?? rowsByRound.count + 1, persona: persona, delta: delta)
        case .councilRoundDone(let round, let score):
            finishRound(round, score: score)
        case .error(let message):
            appendStatus("Error: \(message)")
        default:
            break
        }
    }

    private func configureLayout() {
        stackView.orientation = .vertical
        stackView.alignment = .leading
        stackView.spacing = 12
        stackView.translatesAutoresizingMaskIntoConstraints = false

        scrollView.borderType = .noBorder
        scrollView.hasVerticalScroller = true
        scrollView.translatesAutoresizingMaskIntoConstraints = false

        let documentView = NSView()
        documentView.translatesAutoresizingMaskIntoConstraints = false
        documentView.addSubview(stackView)
        scrollView.documentView = documentView

        addSubview(scrollView)

        NSLayoutConstraint.activate([
            scrollView.leadingAnchor.constraint(equalTo: leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: trailingAnchor),
            scrollView.topAnchor.constraint(equalTo: topAnchor),
            scrollView.bottomAnchor.constraint(equalTo: bottomAnchor),
            documentView.widthAnchor.constraint(equalTo: scrollView.contentView.widthAnchor),
            stackView.leadingAnchor.constraint(equalTo: documentView.leadingAnchor, constant: 16),
            stackView.trailingAnchor.constraint(equalTo: documentView.trailingAnchor, constant: -16),
            stackView.topAnchor.constraint(equalTo: documentView.topAnchor, constant: 16),
            stackView.bottomAnchor.constraint(lessThanOrEqualTo: documentView.bottomAnchor, constant: -16)
        ])
    }

    private func rowForRound(_ round: Int) -> RoundRow {
        if let existing = rowsByRound[round] {
            return existing
        }

        let row = RoundRow(round: round, layer: "Round \(round)")
        rowsByRound[round] = row
        stackView.addArrangedSubview(row.container)
        return row
    }
}
