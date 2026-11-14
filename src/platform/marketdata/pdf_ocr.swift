import Foundation
import PDFKit
import Vision
import AppKit

// Local, bounded recognition; no network or model-generated reconstruction.
guard CommandLine.arguments.count == 2,
      let document = PDFDocument(url: URL(fileURLWithPath: CommandLine.arguments[1])),
      document.pageCount > 0, document.pageCount <= 8 else { exit(2) }
var pages: [[String: Any]] = []
for index in 0..<document.pageCount {
    guard let page = document.page(at: index) else { exit(3) }
    let bounds = page.bounds(for: .mediaBox)
    let scale = min(3.0, 2600.0 / max(bounds.width, bounds.height))
    let width = Int(bounds.width * scale), height = Int(bounds.height * scale)
    guard width > 0, height > 0,
          let context = CGContext(data: nil, width: width, height: height,
              bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { exit(4) }
    context.setFillColor(CGColor(gray: 1, alpha: 1))
    context.fill(CGRect(x: 0, y: 0, width: width, height: height))
    context.scaleBy(x: scale, y: scale)
    page.draw(with: .mediaBox, to: context)
    guard let image = context.makeImage() else { exit(5) }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: image).perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first }
    // Drop uncertain stamps/signatures from the recognized body, but disclose
    // their positions. They must never supply dates or regulatory decisions.
    pages.append(["page": index + 1, "text": lines.filter { $0.confidence >= 0.6 }.map { $0.string }.joined(separator: "\n"),
                  "minimum_confidence": lines.map { $0.confidence }.min() ?? 0,
                  "reliable_fraction": Float(lines.filter { $0.confidence >= 0.6 }.count) / Float(max(1, lines.count)),
                  "low_confidence_lines": lines.enumerated().filter { $0.element.confidence < 0.6 }.map { $0.offset + 1 }])
}
let output = try JSONSerialization.data(withJSONObject: ["engine": "apple_vision", "pages": pages])
FileHandle.standardOutput.write(output)
