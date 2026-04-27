import AppKit
import Foundation

enum MarkdownRenderer {
    static func render(
        _ markdown: String,
        baseFont: NSFont = .systemFont(ofSize: 13),
        textColor: NSColor = .labelColor
    ) -> NSAttributedString {
        if #available(macOS 12.0, *) {
            do {
                let attributed = try AttributedString(
                    markdown: markdown,
                    options: AttributedString.MarkdownParsingOptions(
                        interpretedSyntax: .inlineOnlyPreservingWhitespace
                    )
                )

                let rendered = NSMutableAttributedString(attributedString: NSAttributedString(attributed))
                rendered.addAttributes(
                    [
                        .font: baseFont,
                        .foregroundColor: textColor
                    ],
                    range: NSRange(location: 0, length: rendered.length)
                )
                return rendered
            } catch {
                return plain(markdown, baseFont: baseFont, textColor: textColor)
            }
        }

        return plain(markdown, baseFont: baseFont, textColor: textColor)
    }

    static func renderDocument(
        _ markdown: String,
        baseFont: NSFont = .systemFont(ofSize: 13),
        textColor: NSColor = .labelColor
    ) -> NSAttributedString {
        let rendered = NSMutableAttributedString()
        let blocks = markdown.components(separatedBy: "\n")

        for line in blocks {
            rendered.append(renderLine(line, baseFont: baseFont, textColor: textColor))
            rendered.append(NSAttributedString(string: "\n"))
        }

        return rendered
    }

    private static func renderLine(
        _ line: String,
        baseFont: NSFont,
        textColor: NSColor
    ) -> NSAttributedString {
        let trimmed = line.trimmingCharacters(in: .whitespaces)

        if trimmed.hasPrefix("### ") {
            return plain(String(trimmed.dropFirst(4)), baseFont: .boldSystemFont(ofSize: 15), textColor: textColor)
        }

        if trimmed.hasPrefix("## ") {
            return plain(String(trimmed.dropFirst(3)), baseFont: .boldSystemFont(ofSize: 17), textColor: textColor)
        }

        if trimmed.hasPrefix("# ") {
            return plain(String(trimmed.dropFirst(2)), baseFont: .boldSystemFont(ofSize: 21), textColor: textColor)
        }

        return render(line, baseFont: baseFont, textColor: textColor)
    }

    private static func plain(
        _ string: String,
        baseFont: NSFont,
        textColor: NSColor
    ) -> NSAttributedString {
        NSAttributedString(
            string: string,
            attributes: [
                .font: baseFont,
                .foregroundColor: textColor
            ]
        )
    }
}
