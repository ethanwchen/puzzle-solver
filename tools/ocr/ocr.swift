// Native macOS OCR (Vision). Usage: ocr IMAGE [--json]
// Prints one line per text line: x0 y0 x1 y1 (fractions of the image, top-left origin) <tab> text
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count > 1, let img = NSImage(contentsOfFile: args[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
  FileHandle.standardError.write("usage: ocr IMAGE\n".data(using: .utf8)!); exit(1)
}
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false  // puzzles are full of non-words; don't "fix" them
try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
for obs in (req.results ?? []) {
  guard let top = obs.topCandidates(1).first else { continue }
  let b = obs.boundingBox  // normalized, bottom-left origin
  print(String(format: "%.3f %.3f %.3f %.3f\t%@", b.minX, 1 - b.maxY, b.maxX, 1 - b.minY, top.string))
}
