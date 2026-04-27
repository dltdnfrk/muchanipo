import AppKit

final class InterviewView: NSView {
    struct Option: Equatable {
        let id: String
        let title: String

        init(id: String, title: String) {
            self.id = id
            self.title = title
        }
    }

    var onSubmit: ((String, String) -> Void)?

    private let stackView = NSStackView()
    private let titleLabel = NSTextField(labelWithString: "Interview")
    private let questionLabel = NSTextField(wrappingLabelWithString: "")
    private let optionsStackView = NSStackView()
    private let submitButton = NSButton(title: "Continue", target: nil, action: nil)

    private var questionID = ""
    private var options: [Option] = []
    private var optionButtons: [NSButton] = []

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        configureLayout()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        configureLayout()
    }

    func configure(questionID: String, text: String, options: [Option]) {
        self.questionID = questionID
        self.options = options
        questionLabel.stringValue = text
        rebuildOptions()
        submitButton.isEnabled = !options.isEmpty
        isHidden = false
    }

    func configure(question: InterviewQuestion) {
        configure(
            questionID: question.qID,
            text: question.text,
            options: question.options.enumerated().map { index, option in
                let fallback = "Option \(index + 1)"
                let id = option.id ?? option.value ?? option.label ?? option.text ?? fallback
                let title = option.label ?? option.text ?? option.value ?? option.id ?? fallback
                return Option(id: id, title: title)
            }
        )
    }

    func clear() {
        questionID = ""
        options = []
        questionLabel.stringValue = ""
        optionButtons.forEach { $0.removeFromSuperview() }
        optionButtons.removeAll()
        submitButton.isEnabled = false
    }

    private func configureLayout() {
        wantsLayer = true
        layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor

        stackView.orientation = .vertical
        stackView.alignment = .leading
        stackView.spacing = 12
        stackView.translatesAutoresizingMaskIntoConstraints = false

        titleLabel.font = .boldSystemFont(ofSize: 15)
        titleLabel.textColor = .secondaryLabelColor

        questionLabel.font = .systemFont(ofSize: 15)
        questionLabel.textColor = .labelColor
        questionLabel.lineBreakMode = .byWordWrapping
        questionLabel.maximumNumberOfLines = 0

        optionsStackView.orientation = .vertical
        optionsStackView.alignment = .leading
        optionsStackView.spacing = 8

        submitButton.target = self
        submitButton.action = #selector(submitSelection)
        submitButton.bezelStyle = .rounded
        submitButton.isEnabled = false

        addSubview(stackView)
        stackView.addArrangedSubview(titleLabel)
        stackView.addArrangedSubview(questionLabel)
        stackView.addArrangedSubview(optionsStackView)
        stackView.addArrangedSubview(submitButton)

        NSLayoutConstraint.activate([
            stackView.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 16),
            stackView.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -16),
            stackView.topAnchor.constraint(equalTo: topAnchor, constant: 16),
            stackView.bottomAnchor.constraint(lessThanOrEqualTo: bottomAnchor, constant: -16),
            questionLabel.widthAnchor.constraint(equalTo: stackView.widthAnchor)
        ])
    }

    private func rebuildOptions() {
        optionButtons.forEach { $0.removeFromSuperview() }
        optionButtons.removeAll()

        for (index, option) in options.enumerated() {
            let button = NSButton(radioButtonWithTitle: option.title, target: self, action: #selector(selectOption(_:)))
            button.tag = index
            button.font = .systemFont(ofSize: 13)
            button.lineBreakMode = .byWordWrapping
            button.setButtonType(.radio)
            button.state = index == 0 ? .on : .off
            optionsStackView.addArrangedSubview(button)
            optionButtons.append(button)
        }
    }

    @objc private func selectOption(_ sender: NSButton) {
        for button in optionButtons {
            button.state = button === sender ? .on : .off
        }
    }

    @objc private func submitSelection() {
        guard let selected = optionButtons.first(where: { $0.state == .on }) else {
            return
        }

        let option = options[selected.tag]
        onSubmit?(questionID, option.id)
    }
}
