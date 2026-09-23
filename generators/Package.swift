// swift-tools-version: 6.0
// The card catalog generators, moved here from the MTGImageHash repository:
// image feature prints (macOS only: Vision), pull odds and the price catalog.
import PackageDescription

let package = Package(
    name: "generators",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "GeneratorSupport"),
        .testTarget(name: "GeneratorSupportTests", dependencies: ["GeneratorSupport"]),
        .executableTarget(name: "ImageHashIndexer"),
        .executableTarget(name: "PullOdds", dependencies: ["GeneratorSupport"]),
        .executableTarget(name: "Prices", dependencies: ["GeneratorSupport"]),
    ],
    swiftLanguageModes: [.v5]
)
