// swift-tools-version: 5.9
import PackageDescription

// CarDash: the live macOS dashboard client for the car-logger dash server
// (phase 2 of the vehicle-computer project). SwiftUI + Charts, macOS 14+,
// zero third-party dependencies. Open this folder in Xcode on a Mac
// (File > Open > CarDash) and run the CarDash scheme with ⌘R.
let package = Package(
    name: "CarDash",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "CarDash", targets: ["CarDash"]),
    ],
    targets: [
        .executableTarget(
            name: "CarDash",
            path: "Sources/CarDash"),
    ]
)
