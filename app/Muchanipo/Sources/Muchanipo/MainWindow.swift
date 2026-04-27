import AppKit

final class MainWindowController: NSWindowController {
    private let topicField = NSTextField(string: "")
    private let startButton = NSButton(title: "▶ 시작", target: nil, action: nil)
    private let stopButton = NSButton(title: "■ 중지", target: nil, action: nil)
    private let outputView = NSTextView()
    private let scrollView = NSScrollView()
    private let runner = PythonRunner()

    convenience init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 900, height: 640),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Muchanipo"
        window.center()
        window.minSize = NSSize(width: 640, height: 400)
        self.init(window: window)

        configureContent()
        configureRunner()
    }

    private func configureContent() {
        guard let window else { return }

        let topicLabel = NSTextField(labelWithString: "Topic:")
        topicField.placeholderString = "예: AI 코딩 도우미 시장 분석"
        topicField.stringValue = ""
        topicField.translatesAutoresizingMaskIntoConstraints = false

        startButton.bezelStyle = .rounded
        startButton.target = self
        startButton.action = #selector(handleStart)
        startButton.keyEquivalent = "\r"

        stopButton.bezelStyle = .rounded
        stopButton.target = self
        stopButton.action = #selector(handleStop)
        stopButton.isEnabled = false

        let topRow = NSStackView(views: [topicLabel, topicField, startButton, stopButton])
        topRow.orientation = .horizontal
        topRow.spacing = 8
        topRow.alignment = .centerY
        topRow.distribution = .fill
        topRow.setHuggingPriority(.defaultHigh, for: .horizontal)
        topicField.setContentHuggingPriority(.defaultLow, for: .horizontal)

        outputView.isEditable = false
        outputView.isRichText = false
        outputView.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        outputView.autoresizingMask = [.width]
        outputView.textContainerInset = NSSize(width: 6, height: 6)
        outputView.string = "[ready] Topic 입력 후 ▶ 시작 클릭\n"

        scrollView.hasVerticalScroller = true
        scrollView.borderType = .bezelBorder
        scrollView.documentView = outputView
        scrollView.translatesAutoresizingMaskIntoConstraints = false

        let stack = NSStackView(views: [topRow, scrollView])
        stack.orientation = .vertical
        stack.spacing = 8
        stack.edgeInsets = NSEdgeInsets(top: 12, left: 12, bottom: 12, right: 12)
        stack.alignment = .leading
        stack.distribution = .fill
        stack.translatesAutoresizingMaskIntoConstraints = false

        let content = NSView()
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.topAnchor.constraint(equalTo: content.topAnchor),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            scrollView.leadingAnchor.constraint(equalTo: stack.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: stack.trailingAnchor)
        ])
        window.contentView = content
    }

    private func configureRunner() {
        runner.onOutputLine = { [weak self] line in
            self?.appendOutput(line)
        }
        runner.onTermination = { [weak self] code in
            self?.appendOutput("[exit code=\(code)]")
            self?.setRunning(false)
        }
    }

    @objc private func handleStart() {
        let topic = topicField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !topic.isEmpty else {
            appendOutput("[error] Topic 비어 있음")
            return
        }
        outputView.string = ""
        appendOutput("[start] python3 -m muchanipo serve --topic \"\(topic)\"")
        setRunning(true)
        do {
            try runner.start(topic: topic)
        } catch {
            appendOutput("[error] launch failed: \(error.localizedDescription)")
            setRunning(false)
        }
    }

    @objc private func handleStop() {
        runner.stop()
    }

    private func setRunning(_ running: Bool) {
        startButton.isEnabled = !running
        stopButton.isEnabled = running
        topicField.isEnabled = !running
    }

    private func appendOutput(_ line: String) {
        let suffix = line.hasSuffix("\n") ? line : line + "\n"
        if Thread.isMainThread {
            outputView.textStorage?.append(NSAttributedString(string: suffix))
            outputView.scrollToEndOfDocument(nil)
        } else {
            DispatchQueue.main.async { [weak self] in
                self?.outputView.textStorage?.append(NSAttributedString(string: suffix))
                self?.outputView.scrollToEndOfDocument(nil)
            }
        }
    }
}
