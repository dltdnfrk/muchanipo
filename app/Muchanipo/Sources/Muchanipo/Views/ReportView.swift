import AppKit

final class ReportView: NSView {
    private let scrollView = NSScrollView()
    private let textView = NSTextView()
    private var chunks: [(section: String, markdown: String)] = []

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        configureLayout()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        configureLayout()
    }

    func clear() {
        chunks.removeAll()
        textView.textStorage?.setAttributedString(NSAttributedString())
    }

    func appendChunk(section: String, markdown: String) {
        chunks.append((section: section, markdown: markdown))
        renderChunks()
        isHidden = false
    }

    func setMarkdown(_ markdown: String) {
        chunks = [(section: "report", markdown: markdown)]
        renderChunks()
        isHidden = false
    }

    func loadReport(at url: URL) throws {
        let markdown = try String(contentsOf: url, encoding: .utf8)
        setMarkdown(markdown)
    }

    func apply(_ event: BackendEvent) {
        switch event {
        case .reportChunk(let section, let markdown):
            appendChunk(section: section ?? "report", markdown: markdown)
        case .done(let reportPath):
            guard let reportPath else {
                return
            }

            do {
                try loadReport(at: URL(fileURLWithPath: reportPath))
            } catch {
                appendChunk(section: "error", markdown: "Failed to load report: \(error.localizedDescription)")
            }
        default:
            break
        }
    }

    private func configureLayout() {
        scrollView.borderType = .noBorder
        scrollView.hasVerticalScroller = true
        scrollView.translatesAutoresizingMaskIntoConstraints = false

        textView.isEditable = false
        textView.isSelectable = true
        textView.drawsBackground = false
        textView.textContainerInset = NSSize(width: 16, height: 16)
        textView.textContainer?.widthTracksTextView = true
        textView.font = .systemFont(ofSize: 13)

        scrollView.documentView = textView
        addSubview(scrollView)

        NSLayoutConstraint.activate([
            scrollView.leadingAnchor.constraint(equalTo: leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: trailingAnchor),
            scrollView.topAnchor.constraint(equalTo: topAnchor),
            scrollView.bottomAnchor.constraint(equalTo: bottomAnchor)
        ])
    }

    private func renderChunks() {
        let markdown = chunks.map { chunk in
            chunk.section == "report" ? chunk.markdown : "## \(chunk.section)\n\n\(chunk.markdown)"
        }.joined(separator: "\n\n")

        let rendered = MarkdownRenderer.renderDocument(markdown)
        textView.textStorage?.setAttributedString(rendered)
        scrollToBottom()
    }

    private func scrollToBottom() {
        guard let textStorage = textView.textStorage else {
            return
        }

        textView.scrollRangeToVisible(NSRange(location: textStorage.length, length: 0))
    }
}
