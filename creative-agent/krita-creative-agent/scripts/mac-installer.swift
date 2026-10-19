import AppKit
import CryptoKit
import Foundation

struct InstallerFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct InstallationResult {
    let succeeded: Bool
    let message: String
    let details: [String: Any]
}

struct InstallerRunner {
    static func checksum(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hash = SHA256()
        while let data = try handle.read(upToCount: 1_048_576), !data.isEmpty { hash.update(data: data) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }

    static func run(resources: URL, project: URL?, verifyOnly: Bool = false) -> InstallationResult {
        do {
            let integrityURL = resources.appendingPathComponent("installer-integrity.json")
            let data = try Data(contentsOf: integrityURL)
            guard let integrity = try JSONSerialization.jsonObject(with: data) as? [String: String] else {
                throw InstallerFailure(message: "The installer is incomplete. Download a fresh copy.")
            }
            let node = resources.appendingPathComponent("release/runtime/bin/node")
            let script = resources.appendingPathComponent("install-release.mjs")
            for (key, url) in [("node_sha256", node), ("installer_sha256", script), ("manifest_sha256", resources.appendingPathComponent("release/release-manifest.json"))] {
                guard try checksum(url) == integrity[key] else {
                    throw InstallerFailure(message: "The installer is damaged or changed. Download a fresh copy.")
                }
            }
            let process = Process()
            process.executableURL = node
            var arguments = [script.path, "--bundle", resources.appendingPathComponent("release").path]
            if verifyOnly { arguments.append("--verify") }
            else {
                guard let project = project else { throw InstallerFailure(message: "Choose a folder for your paintings.") }
                arguments += ["--project", project.path]
            }
            process.arguments = arguments
            // The bundled runtime supplies all dependencies. Never inherit NODE_OPTIONS
            // or module-search variables that can inject unrelated startup code.
            process.environment = ["HOME": NSHomeDirectory(), "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"]
            process.currentDirectoryURL = resources
            let output = Pipe(); process.standardOutput = output; process.standardError = output
            try process.run()
            let responseData = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let response = String(data: responseData, encoding: .utf8) ?? ""
            var result: [String: Any] = [:]
            for line in response.split(separator: "\n").reversed() {
                if let lineData = String(line).data(using: .utf8),
                   let parsed = try? JSONSerialization.jsonObject(with: lineData) as? [String: Any] {
                    result = parsed; break
                }
            }
            if process.terminationStatus != 0 {
                return InstallationResult(succeeded: false, message: result["error"] as? String ?? "Installation could not finish. No painting was changed.", details: result)
            }
            return InstallationResult(succeeded: true, message: verifyOnly ? "Installer payload verified." : "Creative Agent is installed.", details: result)
        } catch {
            return InstallationResult(succeeded: false, message: error.localizedDescription, details: [:])
        }
    }
}

final class InstallerApp: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var folderButton: NSButton!
    var installButton: NSButton!
    var folderLabel: NSTextField!
    var status: NSTextField!
    var progress: NSProgressIndicator!
    var project: URL?
    var installing = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        let menu = NSMenu()
        let applicationItem = NSMenuItem(); menu.addItem(applicationItem)
        let applicationMenu = NSMenu(); applicationMenu.addItem(withTitle: "Quit Creative Agent Setup", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        applicationItem.submenu = applicationMenu; NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 600, height: 470), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Creative Agent Setup"
        window.delegate = self
        window.center()
        let body = NSView(); window.contentView = body
        let stack = NSStackView(); stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 18
        stack.translatesAutoresizingMaskIntoConstraints = false; body.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: body.leadingAnchor, constant: 32), stack.trailingAnchor.constraint(equalTo: body.trailingAnchor, constant: -32), stack.topAnchor.constraint(equalTo: body.topAnchor, constant: 32)])
        let title = label("A creative partner, inside Krita.", size: 27, weight: .semibold)
        stack.addArrangedSubview(title)
        let intro = label("Chat about your canvas, develop a plan, and paint with an agent. Everything installs for your Mac user account.", size: 14)
        intro.textColor = .secondaryLabelColor; stack.addArrangedSubview(intro)
        let separator = NSBox(); separator.boxType = .separator; stack.addArrangedSubview(separator)
        stack.addArrangedSubview(label("Where do you keep your paintings?", size: 15, weight: .semibold))
        folderLabel = label("Choose an existing folder. Your paintings stay in ordinary Krita files.", size: 13)
        folderLabel.textColor = .secondaryLabelColor; folderLabel.setAccessibilityLabel("Selected painting folder"); stack.addArrangedSubview(folderLabel)
        folderButton = NSButton(title: "Choose folder…", target: self, action: #selector(chooseFolder))
        folderButton.bezelStyle = .rounded; stack.addArrangedSubview(folderButton)
        let row = NSStackView(); row.orientation = .horizontal; row.spacing = 12
        installButton = NSButton(title: "Install Creative Agent", target: self, action: #selector(install))
        installButton.bezelStyle = .rounded; installButton.keyEquivalent = "\r"; installButton.isEnabled = false
        row.addArrangedSubview(installButton)
        progress = NSProgressIndicator(); progress.style = .spinning; progress.controlSize = .small; progress.isDisplayedWhenStopped = false; row.addArrangedSubview(progress)
        stack.addArrangedSubview(row)
        status = label("Your artwork, API connections and open Krita windows stay untouched. An existing plugin is backed up before updating.", size: 12)
        status.textColor = .secondaryLabelColor; status.setAccessibilityLabel("Installation status"); stack.addArrangedSubview(status)
        for view in [title, intro, folderLabel!, status!] {
            view.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        }
        separator.widthAnchor.constraint(equalTo: stack.widthAnchor).isActive = true
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }

    func label(_ text: String, size: CGFloat, weight: NSFont.Weight = .regular) -> NSTextField {
        let field = NSTextField(wrappingLabelWithString: text)
        field.font = .systemFont(ofSize: size, weight: weight)
        field.isSelectable = true; field.maximumNumberOfLines = 0
        return field
    }

    @objc func chooseFolder() {
        let picker = NSOpenPanel()
        picker.title = "Choose your painting folder"
        picker.prompt = "Use this folder"
        picker.canChooseDirectories = true; picker.canChooseFiles = false; picker.allowsMultipleSelection = false
        picker.canCreateDirectories = true
        picker.directoryURL = project ?? FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
        picker.beginSheetModal(for: window) { [weak self] response in
            guard let self = self, response == .OK, let url = picker.url else { return }
            self.project = url; self.folderLabel.stringValue = url.path; self.installButton.isEnabled = true
        }
    }

    @objc func install() {
        guard let project = project, let resources = Bundle.main.resourceURL, !installing else { return }
        installing = true; installButton.isEnabled = false; folderButton.isEnabled = false
        status.stringValue = "Verifying the release and installing its bundled components…"
        progress.startAnimation(nil)
        DispatchQueue.global(qos: .userInitiated).async {
            let result = InstallerRunner.run(resources: resources, project: project)
            DispatchQueue.main.async { [weak self] in
                guard let self = self else { return }
                self.installing = false; self.progress.stopAnimation(nil); self.folderButton.isEnabled = true
                if result.succeeded {
                    self.installButton.title = "Installed"; self.installButton.isEnabled = false
                    self.status.stringValue = "Installed. Save your work, then restart Krita when ready. If this is your first installation, enable Krita MCP Bridge in Preferences → Python Plugin Manager. Open Settings → Dockers → Creative Agent."
                } else {
                    self.installButton.title = "Try again"; self.installButton.isEnabled = true
                    self.status.stringValue = result.message
                }
            }
        }
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if installing {
            status.stringValue = "Finishing the current installation safely. This window can close when it completes."
            return false
        }
        return true
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply { installing ? .terminateCancel : .terminateNow }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct CreativeAgentSetup {
    static func main() {
        if CommandLine.arguments.contains("--verify-bundle") {
            guard let resources = Bundle.main.resourceURL else { fputs("Missing app resources.\n", stderr); exit(1) }
            let result = InstallerRunner.run(resources: resources, project: nil, verifyOnly: true)
            var details = result.details; details["message"] = result.message
            if let data = try? JSONSerialization.data(withJSONObject: details, options: [.sortedKeys]), let text = String(data: data, encoding: .utf8) { print(text) }
            exit(result.succeeded ? 0 : 1)
        }
        let application = NSApplication.shared
        let delegate = InstallerApp(); application.delegate = delegate
        application.run()
        withExtendedLifetime(delegate) {}
    }
}
