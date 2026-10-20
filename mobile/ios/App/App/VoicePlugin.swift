import Foundation
import AVFoundation
import Speech
import Capacitor

/**
 Push-to-talk speech recognition for voice commands.

 Uses Apple's Speech framework, on-device when the phone supports it, so no
 audio leaves the phone. Streams partial transcripts to JS as `partial`
 events and finishes with a single `final` event (also on silence timeout).

 JS:  Capacitor.Plugins.Voice.available()
      Capacitor.Plugins.Voice.requestPermission()
      Capacitor.Plugins.Voice.start({ lang: "en-US" })
      Capacitor.Plugins.Voice.stop()
      addListener("partial" | "final" | "error", ...)
 */
@objc(VoicePlugin)
public class VoicePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "VoicePlugin"
    public let jsName = "Voice"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "available", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "requestPermission", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise),
    ]

    private let engine = AVAudioEngine()
    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var lastText = ""
    private var silenceTimer: Timer?
    private var maxTimer: Timer?
    private var finished = true

    @objc func available(_ call: CAPPluginCall) {
        let lang = call.getString("lang") ?? Locale.preferredLanguages.first ?? "en-US"
        let r = SFSpeechRecognizer(locale: Locale(identifier: lang))
        call.resolve([
            "available": r?.isAvailable ?? false,
            "onDevice": r?.supportsOnDeviceRecognition ?? false,
            "lang": lang,
        ])
    }

    @objc func requestPermission(_ call: CAPPluginCall) {
        SFSpeechRecognizer.requestAuthorization { status in
            let speechOk = status == .authorized
            AVAudioSession.sharedInstance().requestRecordPermission { micOk in
                call.resolve(["speech": speechOk, "mic": micOk])
            }
        }
    }

    @objc func start(_ call: CAPPluginCall) {
        let lang = call.getString("lang") ?? Locale.preferredLanguages.first ?? "en-US"
        DispatchQueue.main.async {
            self.teardown()
            guard SFSpeechRecognizer.authorizationStatus() == .authorized,
                  AVAudioSession.sharedInstance().recordPermission == .granted else {
                call.reject("permission", "NO_PERMISSION")
                return
            }
            guard let rec = SFSpeechRecognizer(locale: Locale(identifier: lang)), rec.isAvailable else {
                call.reject("Speech recognition is not available for \(lang)", "UNAVAILABLE")
                return
            }
            do {
                let session = AVAudioSession.sharedInstance()
                try session.setCategory(.record, mode: .measurement, options: .duckOthers)
                try session.setActive(true, options: .notifyOthersOnDeactivation)

                let req = SFSpeechAudioBufferRecognitionRequest()
                req.shouldReportPartialResults = true
                req.taskHint = .search
                if rec.supportsOnDeviceRecognition { req.requiresOnDeviceRecognition = true }

                let input = self.engine.inputNode
                let format = input.outputFormat(forBus: 0)
                guard format.sampleRate > 0, format.channelCount > 0 else {
                    call.reject("No microphone input", "NO_INPUT")
                    return
                }
                input.removeTap(onBus: 0)
                input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
                    req.append(buffer)
                }
                self.engine.prepare()
                try self.engine.start()

                self.recognizer = rec
                self.request = req
                self.lastText = ""
                self.finished = false
                self.task = rec.recognitionTask(with: req) { [weak self] result, error in
                    DispatchQueue.main.async {
                        guard let self, !self.finished else { return }
                        if let result {
                            let text = result.bestTranscription.formattedString
                            if text != self.lastText {
                                self.lastText = text
                                self.notifyListeners("partial", data: ["text": text])
                                self.armSilenceTimer()
                            }
                            if result.isFinal { self.finish() }
                        } else if error != nil {
                            // "No speech detected" also lands here: report what we have.
                            if self.lastText.isEmpty {
                                self.notifyListeners("error", data: ["message": "Didn't catch that"])
                                self.teardown()
                            } else {
                                self.finish()
                            }
                        }
                    }
                }
                // Hard cap so the mic never stays open.
                self.maxTimer = Timer.scheduledTimer(withTimeInterval: 12, repeats: false) { [weak self] _ in
                    self?.finish()
                }
                self.armSilenceTimer(initial: true)
                call.resolve(["started": true, "onDevice": req.requiresOnDeviceRecognition, "lang": lang])
            } catch {
                self.teardown()
                call.reject("Could not start the microphone: \(error.localizedDescription)", "START_FAILED")
            }
        }
    }

    @objc func stop(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.finish()
            call.resolve()
        }
    }

    /// Stop after a pause in speech; longer grace before the first word.
    private func armSilenceTimer(initial: Bool = false) {
        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: initial ? 5.0 : 1.4, repeats: false) { [weak self] _ in
            self?.finish()
        }
    }

    private func finish() {
        guard !finished else { return }
        let text = lastText
        teardown()
        if text.isEmpty {
            notifyListeners("error", data: ["message": "Didn't catch that"])
        } else {
            notifyListeners("final", data: ["text": text])
        }
    }

    private func teardown() {
        finished = true
        silenceTimer?.invalidate(); silenceTimer = nil
        maxTimer?.invalidate(); maxTimer = nil
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio(); request = nil
        task?.cancel(); task = nil
        recognizer = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
