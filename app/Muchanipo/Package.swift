// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "Muchanipo",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "Muchanipo", targets: ["Muchanipo"])
    ],
    targets: [
        .executableTarget(
            name: "Muchanipo",
            path: "Sources/Muchanipo"
        )
    ]
)
