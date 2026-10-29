// Nublock.app: la app de macOS de Nublock.
//
// macOS asigna nombre, ícono y permisos (notificaciones, cámara, Screen Recording) a la *app*
// que corre un proceso. Por eso Nublock es un bundle con este programa Swift que:
//   - sin argumentos: lanza y supervisa el proceso de Python (`python -m nublock run`) y, si
//     faltan permisos, muestra la ventana "Permisos y configuración";
//   - muestra notificaciones nativas (`--notify`), con el botón "Falsa alarma";
//   - informa y pide permisos (`--status`, `--request-permissions`, `--onboarding`);
//   - se registra para abrirse al iniciar sesión (`--login-item on|off`).
//
// El Python que ejecuta es el del venv (desarrollo: clave NublockPython del Info.plist) o el que
// viene dentro de la app (release: Contents/Resources/python).
//
// Uso:
//   Nublock                                    lanzar Nublock (doble click, ítem de inicio)
//   Nublock --onboarding                       solo la ventana de permisos
//   Nublock --snapshot archivo.png              dibuja esa ventana a un PNG (documentación/tests)
//   Nublock --notify --title T --message M [--sound Glass] [--dashboard URL] [--false-alarm]
//           [--timeout SEGUNDOS]
//   Nublock --status                           permisos en JSON
//   Nublock --request-permissions              pedir los permisos que falten
//   Nublock --login-item on|off                abrir Nublock al iniciar sesión

import AVFoundation
import AppKit
import CoreGraphics
import ServiceManagement
import UserNotifications

let falseAlarmAction = "FALSE_ALARM"
let alertCategory = "NUBLOCK_ALERT"
let alreadyRunningExitCode: Int32 = 3  // `nublock run` sale con 3 si ya hay otra instancia
let launchAgentLabel = "local.nublock.autostart"

/// Valor que sigue a `name` en los argumentos, ej. option("--title").
func option(_ name: String) -> String? {
    let args = CommandLine.arguments
    guard let index = args.firstIndex(of: name), index + 1 < args.count else { return nil }
    return args[index + 1]
}

func has(_ flag: String) -> Bool { CommandLine.arguments.contains(flag) }

/// Valor propio guardado en el Info.plist al construir la app (ver app_bundle.py).
func infoValue(_ key: String) -> String? { Bundle.main.object(forInfoDictionaryKey: key) as? String }

let home = FileManager.default.homeDirectoryForCurrentUser
let dataDir = home.appendingPathComponent("Library/Application Support/nublock")
let resources = Bundle.main.resourceURL ?? URL(fileURLWithPath: "/")

// MARK: - Ejecutar Python (el de la app o el del venv)

func pythonPath() -> String {
    if let python = infoValue("NublockPython"), FileManager.default.fileExists(atPath: python) {
        return python  // desarrollo: el venv del repo
    }
    return resources.appendingPathComponent("python/bin/python3").path  // release
}

/// Un proceso `python -m nublock <args>` con el entorno que Nublock necesita.
func nublockProcess(_ args: [String]) -> Process {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: pythonPath())
    process.arguments = ["-m", "nublock"] + args
    process.currentDirectoryURL = home
    var environment = ProcessInfo.processInfo.environment
    environment["NUBLOCK_APP"] = Bundle.main.bundlePath  // así Python sabe qué app notifica
    let models = resources.appendingPathComponent("models")
    if FileManager.default.fileExists(atPath: models.path) {
        environment["NUBLOCK_MODELS_DIR"] = models.path
    }
    process.environment = environment
    let logs = home.appendingPathComponent("Library/Logs/nublock")
    try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
    let logFile = logs.appendingPathComponent("app.log")
    if !FileManager.default.fileExists(atPath: logFile.path) {
        FileManager.default.createFile(atPath: logFile.path, contents: nil)
    }
    if let handle = try? FileHandle(forWritingTo: logFile) {
        handle.seekToEndOfFile()
        process.standardOutput = handle
        process.standardError = handle
    }
    return process
}

/// Primera vez (release): copia el config de ejemplo que viene en la app.
func ensureUserConfig() {
    let config = dataDir.appendingPathComponent("config.yaml")
    let example = resources.appendingPathComponent("config.example.yaml")
    let manager = FileManager.default
    if !manager.fileExists(atPath: config.path) && manager.fileExists(atPath: example.path) {
        try? manager.createDirectory(at: dataDir, withIntermediateDirectories: true)
        try? manager.copyItem(at: example, to: config)
    }
}

// MARK: - Permisos

enum PermissionState { case granted, missing, denied }

func notificationState(_ done: @escaping (PermissionState) -> Void) {
    UNUserNotificationCenter.current().getNotificationSettings { settings in
        switch settings.authorizationStatus {
        case .authorized, .provisional: done(.granted)
        case .denied: done(.denied)
        default: done(.missing)
        }
    }
}

func notificationStatus() -> String {
    let semaphore = DispatchSemaphore(value: 0)
    var status = "unknown"
    notificationState { state in
        status = state == .granted ? "granted" : (state == .denied ? "denied" : "not_determined")
        semaphore.signal()
    }
    _ = semaphore.wait(timeout: .now() + 5)
    return status
}

func cameraState() -> PermissionState {
    switch AVCaptureDevice.authorizationStatus(for: .video) {
    case .authorized: return .granted
    case .denied, .restricted: return .denied
    default: return .missing
    }
}

func cameraStatus() -> String {
    switch AVCaptureDevice.authorizationStatus(for: .video) {
    case .authorized: return "granted"
    case .denied, .restricted: return "denied"
    case .notDetermined: return "not_determined"
    @unknown default: return "unknown"
    }
}

var launchAgentURL: URL { home.appendingPathComponent("Library/LaunchAgents/\(launchAgentLabel).plist") }

func loginItemEnabled() -> Bool {
    SMAppService.mainApp.status == .enabled
        || FileManager.default.fileExists(atPath: launchAgentURL.path)
}

func loginItemStatus() -> String {
    if FileManager.default.fileExists(atPath: launchAgentURL.path) { return "enabled" }
    switch SMAppService.mainApp.status {
    case .enabled: return "enabled"
    case .requiresApproval: return "requires_approval"
    case .notRegistered: return "not_registered"
    case .notFound: return "not_found"
    @unknown default: return "unknown"
    }
}

func printStatus() {
    let status: [String: String] = [
        "notifications": notificationStatus(),
        "camera": cameraStatus(),
        "screen_recording": CGPreflightScreenCaptureAccess() ? "granted" : "not_granted",
        "login_item": loginItemStatus(),
    ]
    let data = try! JSONSerialization.data(withJSONObject: status, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
}

/// Pide cada permiso que falte. macOS muestra sus diálogos a nombre de "Nublock".
func requestPermissions() {
    let semaphore = DispatchSemaphore(value: 0)
    UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in
        semaphore.signal()
    }
    _ = semaphore.wait(timeout: .now() + 120)
    if AVCaptureDevice.authorizationStatus(for: .video) == .notDetermined {
        AVCaptureDevice.requestAccess(for: .video) { _ in semaphore.signal() }
        _ = semaphore.wait(timeout: .now() + 120)
    }
    if !CGPreflightScreenCaptureAccess() {
        _ = CGRequestScreenCaptureAccess()  // la primera vez lleva a System Settings
    }
    printStatus()
}

func runLaunchctl(_ args: [String]) {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
    process.arguments = args
    try? process.run()
    process.waitUntilExit()
}

/// Abrir al iniciar sesión: SMAppService (Login Items) o, si macOS no lo acepta (puede pasar
/// con apps firmadas ad-hoc), un LaunchAgent que hace `open -a Nublock.app`.
func setLoginItem(_ enabled: Bool) -> Int32 {
    let domain = "gui/\(getuid())"
    if !enabled {
        try? SMAppService.mainApp.unregister()
        runLaunchctl(["bootout", "\(domain)/\(launchAgentLabel)"])
        try? FileManager.default.removeItem(at: launchAgentURL)
        print(loginItemStatus())
        return 0
    }
    if (try? SMAppService.mainApp.register()) != nil, SMAppService.mainApp.status == .enabled {
        print("enabled")
        return 0
    }
    let plist: [String: Any] = [
        "Label": launchAgentLabel,
        "ProgramArguments": ["/usr/bin/open", "-a", Bundle.main.bundlePath],
        "RunAtLoad": true,
    ]
    do {
        try FileManager.default.createDirectory(
            at: launchAgentURL.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try PropertyListSerialization.data(fromPropertyList: plist, format: .xml, options: 0)
        try data.write(to: launchAgentURL)
        runLaunchctl(["bootstrap", domain, launchAgentURL.path])
        print("enabled")
        return 0
    } catch {
        fputs("\(error.localizedDescription)\n", stderr)
        return 1
    }
}

// MARK: - Ventana "Permisos y configuración"

final class OnboardingWindow: NSObject, NSWindowDelegate {
    struct Item {
        let key: String
        let title: String
        let detail: String
        let optional: Bool
    }

    let items = [
        Item(key: "notifications", title: "Notificaciones",
             detail: "Para avisarte cuando te distraes o se cumple una regla.", optional: false),
        Item(key: "camera", title: "Cámara",
             detail: "Solo en focus sessions y procesada en tu Mac. Nunca se graba ni se guarda.",
             optional: false),
        Item(key: "screen", title: "Grabación de pantalla",
             detail: "Para leer títulos de ventana (ej. YouTube en el browser). No graba tu pantalla.",
             optional: true),
        Item(key: "calibration", title: "Calibrar la cámara",
             detail: "Mira el centro y las esquinas de cada monitor (menos de 1 minuto).",
             optional: true),
        Item(key: "sites", title: "Bloqueo de sitios",
             detail: "Instala un helper para bloquear dominios; pide tu contraseña de administrador.",
             optional: true),
        Item(key: "login", title: "Abrir al iniciar sesión",
             detail: "Nublock arranca solo cuando enciendes el Mac.", optional: true),
    ]

    var window: NSWindow?
    var icons: [String: NSImageView] = [:]
    var buttons: [String: NSButton] = [:]
    var timer: Timer?
    var states: [String: PermissionState] = [:]
    var screenGrantedAtStart = CGPreflightScreenCaptureAccess()
    /// Se llama al cerrar la ventana. `true` = Screen Recording se activó (hay que reiniciar).
    var onClose: ((Bool) -> Void)?

    func show(activate: Bool = true) {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 620, height: 470),
            styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Nublock — permisos y configuración"
        window.isReleasedWhenClosed = false
        window.delegate = self

        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        stack.edgeInsets = NSEdgeInsets(top: 22, left: 24, bottom: 22, right: 24)

        let header = NSTextField(labelWithString: "Configura Nublock")
        header.font = .boldSystemFont(ofSize: 18)
        stack.addArrangedSubview(header)
        let intro = NSTextField(wrappingLabelWithString:
            "Todo se procesa en tu Mac: no se envía nada a internet. Las marcadas como opcionales se pueden hacer después.")
        intro.textColor = .secondaryLabelColor
        stack.addArrangedSubview(intro)

        for item in items {
            let icon = NSImageView()
            icon.symbolConfiguration = .init(pointSize: 20, weight: .regular)
            icon.widthAnchor.constraint(equalToConstant: 26).isActive = true
            icons[item.key] = icon

            let title = NSTextField(labelWithString: item.title + (item.optional ? "  (opcional)" : ""))
            title.font = .boldSystemFont(ofSize: 13)
            let detail = NSTextField(wrappingLabelWithString: item.detail)
            detail.textColor = .secondaryLabelColor
            detail.font = .systemFont(ofSize: 11.5)
            detail.preferredMaxLayoutWidth = 400
            let texts = NSStackView(views: [title, detail])
            texts.orientation = .vertical
            texts.alignment = .leading
            texts.spacing = 2

            let button = NSButton(title: "…", target: self, action: #selector(act(_:)))
            button.identifier = NSUserInterfaceItemIdentifier(item.key)
            button.bezelStyle = .rounded
            button.widthAnchor.constraint(equalToConstant: 130).isActive = true
            buttons[item.key] = button

            let row = NSStackView(views: [icon, texts, NSView(), button])
            row.orientation = .horizontal
            row.alignment = .centerY
            row.spacing = 12
            stack.addArrangedSubview(row)
            row.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -48).isActive = true
        }

        let done = NSButton(title: "Listo", target: self, action: #selector(finish))
        done.keyEquivalent = "\r"
        done.bezelStyle = .rounded
        let footer = NSTextField(labelWithString: "Vuelve aquí desde el menú de Nublock → Permisos y configuración.")
        footer.textColor = .tertiaryLabelColor
        footer.font = .systemFont(ofSize: 11)
        let bottom = NSStackView(views: [footer, NSView(), done])
        bottom.orientation = .horizontal
        stack.addArrangedSubview(bottom)
        bottom.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -48).isActive = true

        window.contentView = stack
        window.center()
        self.window = window
        refresh()
        // Se actualiza sola cada segundo (ej. cuando activas un permiso en System Settings).
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in self?.refresh() }
        if activate {
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
        }
    }

    /// Dibuja la ventana a un PNG sin mostrarla (no necesita permiso de grabación de pantalla).
    func snapshot(to path: String) {
        guard let view = window?.contentView,
            let image = view.bitmapImageRepForCachingDisplay(in: view.bounds)
        else { return }
        view.cacheDisplay(in: view.bounds, to: image)
        try? image.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
    }

    func refresh() {
        notificationState { state in DispatchQueue.main.async { self.update("notifications", state) } }
        update("camera", cameraState())
        update("screen", CGPreflightScreenCaptureAccess() ? .granted : .missing)
        let calibration = dataDir.appendingPathComponent("calibration.json")
        update("calibration", FileManager.default.fileExists(atPath: calibration.path) ? .granted : .missing)
        let helper = "/Library/PrivilegedHelperTools/local.nublock.hosts.sh"
        update("sites", FileManager.default.fileExists(atPath: helper) ? .granted : .missing)
        update("login", loginItemEnabled() ? .granted : .missing)
    }

    func update(_ key: String, _ state: PermissionState) {
        states[key] = state
        let (symbol, color): (String, NSColor) = switch state {
        case .granted: ("checkmark.circle.fill", .systemGreen)
        case .missing: ("circle", .tertiaryLabelColor)
        case .denied: ("xmark.circle.fill", .systemRed)
        }
        icons[key]?.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)
        icons[key]?.contentTintColor = color
        let title: String = switch (key, state) {
        case ("calibration", .granted): "Recalibrar"
        case ("login", .granted): "Desactivar"
        case (_, .granted): "Listo ✓"
        case (_, .denied): "Abrir Ajustes"
        case ("calibration", _): "Calibrar"
        case ("sites", _): "Instalar"
        case ("login", _): "Activar"
        default: "Permitir"
        }
        buttons[key]?.title = title
        let finished = state == .granted && !["calibration", "login"].contains(key)
        buttons[key]?.isEnabled = !finished
    }

    @objc func act(_ sender: NSButton) {
        guard let key = sender.identifier?.rawValue else { return }
        let state = states[key] ?? .missing
        let settings = "x-apple.systempreferences:com.apple.preference.security?"
        switch key {
        case "notifications":
            if state == .denied {
                open("x-apple.systempreferences:com.apple.Notifications-Settings.extension")
            } else {
                UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
            }
        case "camera":
            if state == .denied {
                open(settings + "Privacy_Camera")
            } else {
                AVCaptureDevice.requestAccess(for: .video) { _ in }
            }
        case "screen":
            if !CGRequestScreenCaptureAccess() { open(settings + "Privacy_ScreenCapture") }
        case "calibration":
            if cameraState() != .granted {
                alert("Primero permite la cámara.")
                return
            }
            runNublock(["calibrate", "--gui"], button: sender, busy: "Calibrando…")
        case "sites":
            runNublock(["sites", "setup"], button: sender, busy: "Instalando…")
        case "login":
            _ = setLoginItem(state != .granted)
        default:
            break
        }
        refresh()
    }

    func runNublock(_ args: [String], button: NSButton, busy: String) {
        let process = nublockProcess(args)
        process.terminationHandler = { _ in DispatchQueue.main.async { self.refresh() } }
        do {
            try process.run()
            button.title = busy
            button.isEnabled = false
        } catch {
            alert("No se pudo ejecutar Nublock: \(error.localizedDescription)")
        }
    }

    func open(_ url: String) {
        if let url = URL(string: url) { NSWorkspace.shared.open(url) }
    }

    func alert(_ text: String) {
        let alert = NSAlert()
        alert.messageText = text
        alert.runModal()
    }

    @objc func finish() { window?.close() }

    func windowWillClose(_ notification: Notification) {
        timer?.invalidate()
        UserDefaults.standard.set(true, forKey: "onboardingShown")
        onClose?(!screenGrantedAtStart && CGPreflightScreenCaptureAccess())
    }

    /// ¿Mostrarla al abrir la app? La primera vez, o si falta un permiso obligatorio.
    static func needed() -> Bool {
        if !UserDefaults.standard.bool(forKey: "onboardingShown") { return true }
        return cameraState() != .granted || notificationStatus() != "granted"
    }
}

// MARK: - Supervisor del proceso de Python

final class Launcher {
    private var process: Process?
    private var crashes: [Date] = []
    private var restarting = false

    func start() {
        let child = nublockProcess(["run"])
        child.terminationHandler = { finished in
            DispatchQueue.main.async { self.childExited(finished.terminationStatus) }
        }
        do {
            try child.run()
            process = child
        } catch {
            fputs("No se pudo iniciar \(pythonPath()): \(error)\n", stderr)
            NSApp.terminate(nil)
        }
    }

    /// Reinicia Python (ej. Screen Recording solo aplica a procesos nuevos).
    func restart() {
        restarting = true
        process?.terminate()
    }

    private func childExited(_ code: Int32) {
        process = nil
        if restarting {
            restarting = false
            start()
            return
        }
        switch code {
        case 0:  // el usuario eligió "Salir" en el tray
            NSApp.terminate(nil)
        case alreadyRunningExitCode:  // ya estaba corriendo: mostramos el dashboard
            if let dashboard = infoValue("NublockDashboard"), let url = URL(string: dashboard) {
                NSWorkspace.shared.open(url)
            }
            NSApp.terminate(nil)
        default:  // se cayó: reintentar, pero no más de 5 veces en 10 minutos
            let now = Date()
            crashes = crashes.filter { now.timeIntervalSince($0) < 600 } + [now]
            if crashes.count > 5 {
                fputs("Nublock se cayó demasiadas veces; revisa ~/Library/Logs/nublock\n", stderr)
                NSApp.terminate(nil)
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 5) { self.start() }
            }
        }
    }

    func stop() {
        guard let child = process, child.isRunning else { return }
        child.terminate()  // SIGTERM: Nublock cierra sesiones y libera la cámara
        let deadline = Date().addingTimeInterval(5)
        while child.isRunning && Date() < deadline { usleep(100_000) }
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let center = UNUserNotificationCenter.current()
    var launcher: Launcher?
    var onboarding: OnboardingWindow?

    func applicationWillFinishLaunching(_ notification: Notification) {
        // El delegate se asigna antes de terminar de lanzar: así recibimos el click que abrió la app.
        center.delegate = self
        let falseAlarm = UNNotificationAction(
            identifier: falseAlarmAction, title: "Falsa alarma", options: [])
        center.setNotificationCategories([
            UNNotificationCategory(
                identifier: alertCategory, actions: [falseAlarm], intentIdentifiers: [], options: [])
        ])
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        if has("--notify") {
            post()
        } else if has("--status") {
            printStatus()
            exit(0)
        } else if has("--request-permissions") {
            requestPermissions()
            exit(0)
        } else if let value = option("--login-item") {
            exit(setLoginItem(value == "on"))
        } else if let path = option("--snapshot") {
            let window = OnboardingWindow()
            onboarding = window
            NSApp.appearance = NSAppearance(named: .aqua)  // fondo claro en el PNG
            window.show(activate: false)
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {  // espera los estados async
                window.snapshot(to: path)
                exit(0)
            }
        } else if has("--onboarding") {
            showOnboarding { _ in NSApp.terminate(nil) }
        } else {
            ensureUserConfig()
            let launcher = Launcher()
            self.launcher = launcher
            launcher.start()
            if OnboardingWindow.needed() {
                showOnboarding { screenChanged in
                    if screenChanged { launcher.restart() }
                }
            }
        }
    }

    func showOnboarding(onClose: @escaping (Bool) -> Void) {
        let window = OnboardingWindow()
        window.onClose = onClose
        onboarding = window
        window.show()
    }

    // Con la ventana cerrada la app sigue viva (el launcher supervisa Python).
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    func applicationWillTerminate(_ notification: Notification) {
        launcher?.stop()
    }

    func post() {
        let timeout = Double(option("--timeout") ?? "10") ?? 10
        DispatchQueue.main.asyncAfter(deadline: .now() + timeout) {
            fputs("timeout: no se respondió el permiso de notificaciones\n", stderr)
            exit(3)
        }
        // La primera vez macOS pregunta si permites las notificaciones de Nublock.
        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            guard granted else {
                fputs("sin permiso de notificaciones: \(error?.localizedDescription ?? "denegado")\n", stderr)
                exit(2)
            }
            let content = UNMutableNotificationContent()
            content.title = option("--title") ?? "Nublock"
            content.body = option("--message") ?? ""
            if let sound = option("--sound") {
                content.sound = UNNotificationSound(named: UNNotificationSoundName(rawValue: sound + ".aiff"))
            }
            if let dashboard = option("--dashboard") {
                content.userInfo = ["dashboard": dashboard]
            }
            if has("--false-alarm") {
                content.categoryIdentifier = alertCategory  // agrega el botón "Falsa alarma"
            }
            let request = UNNotificationRequest(
                identifier: UUID().uuidString, content: content, trigger: nil)
            self.center.add(request) { error in
                if let error {
                    fputs("\(error.localizedDescription)\n", stderr)
                    exit(1)
                }
                exit(0)
            }
        }
    }

    // Mostrar el banner aunque la app esté activa.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter, willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound, .list])
    }

    // Click en la notificación (abre el dashboard) o en el botón "Falsa alarma".
    func userNotificationCenter(
        _ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let dashboard = response.notification.request.content.userInfo["dashboard"] as? String
        if response.actionIdentifier == falseAlarmAction, let dashboard,
            let url = URL(string: dashboard + "/feedback/false-alarm")
        {
            // Mismo endpoint que el botón del dashboard; solo 127.0.0.1.
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            URLSession.shared.dataTask(with: request) { _, _, _ in completionHandler() }.resume()
            return
        }
        if response.actionIdentifier == UNNotificationDefaultActionIdentifier, let dashboard,
            let url = URL(string: dashboard)
        {
            NSWorkspace.shared.open(url)
        }
        completionHandler()
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)  // sin ícono en el Dock: Nublock vive en la barra de menú
app.run()
