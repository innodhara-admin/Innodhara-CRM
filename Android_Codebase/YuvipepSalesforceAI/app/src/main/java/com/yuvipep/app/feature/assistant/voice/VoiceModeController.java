package com.yuvipep.app.feature.assistant.voice;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.gson.JsonObject;
import com.yuvipep.app.core.net.EnvironmentStore;
import com.yuvipep.app.core.net.dto.AssistantDtos;
import com.yuvipep.app.core.voice.MicStreamer;
import com.yuvipep.app.core.voice.SpeechInput;
import com.yuvipep.app.core.voice.SpeechOutput;
import com.yuvipep.app.core.voice.TtsSpeaker;
import com.yuvipep.app.core.voice.VoicePlayer;
import com.yuvipep.app.feature.assistant.AssistantRepository;
import com.yuvipep.app.feature.assistant.AssistantSession;

import java.io.File;

import javax.inject.Inject;

import dagger.hilt.android.qualifiers.ApplicationContext;
import okhttp3.OkHttpClient;

/**
 * Hands-free Jarvis (backend doc §4–6). One instance per assistant screen;
 * everything here runs on the main thread.
 *
 * <h3>Two paths</h3>
 * <ul>
 *   <li><b>Streaming</b> — the WebSocket: the mic streams 20 ms PCM frames,
 *   the server hears the end of each utterance, and the answer comes back as
 *   a {@code reply} plus, when the server has a voice, 24 kHz audio.</li>
 *   <li><b>One clip at a time</b> — {@code POST /assistant/voice/turn}, used
 *   when the socket cannot even be opened (a proxy without WebSocket
 *   support). The phone detects the end of speech itself, posts the clip,
 *   plays the answer, and listens again.</li>
 * </ul>
 *
 * <h3>Echo</h3>
 * Without a working echo canceller the server would hear Jarvis as a new
 * request. So unless the person has switched "talk over Jarvis" on (and the
 * phone has a canceller), no mic audio is sent while anything is playing, and
 * the mic reopens only once the last sample has actually played
 * ({@link VoicePlayer.Listener#onDrained()}) — the server sends audio faster
 * than real time, so its {@code speak_end} is not that moment.
 *
 * <p>Both paths use {@link AssistantSession}'s id, so typed and spoken turns
 * are one conversation and an unfinished client survives a reconnect.
 */
public class VoiceModeController {

    public enum State {
        /** Not in voice mode. */
        OFF,
        /** Asking the server what it supports / opening the socket. */
        CONNECTING,
        /** Mic open, waiting for the person. */
        LISTENING,
        /** The server hears speech. */
        HEARING,
        /** Speech captured; transcribing. */
        TRANSCRIBING,
        /** Jarvis is working on it. */
        THINKING,
        /** Jarvis is talking. */
        SPEAKING,
        /** The socket dropped; trying again. */
        RECONNECTING,
        /** One-clip path: waiting for a tap to listen again. */
        PAUSED
    }

    /** What the screen shows. Main thread. */
    public interface Ui {
        void onVoiceState(@NonNull State state, @Nullable String detail);

        /** 0..1 microphone loudness for the orb. */
        void onVoiceLevel(float level);

        /** What the server heard — the person's side of the transcript. */
        void onVoiceTranscript(@NonNull String text, boolean lowConfidence);

        /** Jarvis's answer: render exactly like an /assistant/command response. */
        void onVoiceReply(@NonNull AssistantDtos.CommandResponse reply);

        /**
         * Jarvis did not act — the words were too uncertain. {@code reply}
         * says so and asks again; {@code heard} is offered for editing.
         */
        void onVoiceNotActed(@NonNull String reply, @Nullable String heard);

        /** Something went wrong with one turn; the session goes on. */
        void onVoiceError(@NonNull String message);

        /** Voice mode is over. {@code reason} is null when the person ended it. */
        void onVoiceEnded(@Nullable String reason);

        /** The login is no longer accepted. */
        void onVoiceUnauthorized();

        /** What Jarvis is saying right now (for captions). */
        default void onVoiceSpeaking(@NonNull String text) {
        }
    }

    /** What "this" means right now — ContextBus's current entity. */
    public interface ContextSource {
        @Nullable String leadId();

        @Nullable String proposalId();

        @Nullable String meetingId();
    }

    private static final String TAG = "VoiceMode";
    private static final int MAX_RECONNECTS = 5;
    private static final long FIRST_BACKOFF_MS = 1_000L;
    private static final long MAX_BACKOFF_MS = 15_000L;
    /** The server refuses longer text turns (and then no turn is counted). */
    private static final int MAX_TEXT = 4000;

    private final Context app;
    private final OkHttpClient httpClient;
    private final EnvironmentStore environment;
    private final AssistantRepository repository;
    private final AssistantSession session;
    private final TtsSpeaker deviceVoice;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final VoicePrefs prefs;

    @Nullable private Ui ui;
    @Nullable private ContextSource context;

    private State state = State.OFF;
    /** Changes whenever voice mode starts or stops: late callbacks compare it. */
    private int epoch;

    // Streaming path
    /** Volatile: the mic capture thread sends through it. */
    @Nullable private volatile VoiceSocket socket;
    @Nullable private MicStreamer mic;
    /** Where Jarvis's voice comes out: our own player, or the avatar's. */
    @Nullable private SpeechOutput player;
    /** {@link #player} belongs to the caller (the avatar) — never released here. */
    private boolean externalOutput;
    /** An output waiting for the current speech to finish before taking over. */
    @Nullable private SpeechOutput pendingOutput;
    private boolean ready;
    private boolean bargeIn;
    private boolean serverVoice;
    private int reconnects;
    /** Turns the server has queued but not answered yet. */
    private int pendingTurns;
    /**
     * Speech was silenced here: audio still in flight for it is dropped until
     * the server announces new speech with {@code speak_start}.
     */
    private boolean dropAudio;

    // One-clip path
    private boolean clipMode;
    @Nullable private SpeechInput clipInput;
    private boolean clipBusy;

    /** The server voice to speak with (the avatar's); null = server default. */
    @Nullable private String voiceName;

    /** The person muted the microphone; nothing is sent until unmuted. */
    private boolean muted;

    /** The device voice is speaking something from this epoch. */
    private boolean deviceSpeaking;
    private int deviceSpeechToken;

    @Nullable private AudioFocusRequest focusRequest;

    @Inject
    public VoiceModeController(@ApplicationContext Context app, OkHttpClient httpClient,
                               EnvironmentStore environment, AssistantRepository repository,
                               AssistantSession session, TtsSpeaker deviceVoice) {
        this.app = app;
        this.httpClient = httpClient;
        this.environment = environment;
        this.repository = repository;
        this.session = session;
        this.deviceVoice = deviceVoice;
        this.prefs = new VoicePrefs(app);
    }

    public boolean isActive() {
        return state != State.OFF;
    }

    @NonNull
    public State state() {
        return state;
    }

    /** Typed turns go over the socket (streaming path only). */
    public boolean canSendText() {
        return isActive() && !clipMode && ready && socket != null;
    }

    /** Whether the phone can let the person talk over Jarvis at all. */
    public static boolean bargeInSupported() {
        return MicStreamer.echoCancellerAvailable();
    }

    public boolean bargeInPreferred() {
        return prefs.bargeIn();
    }

    /** Takes effect on the next connection (the server fixes it at start). */
    public void setBargeInPreferred(boolean enabled) {
        prefs.setBargeIn(enabled);
        if (isActive() && !clipMode && ready) reconnectNow();
    }

    /**
     * Begin voice mode. The caller has already checked RECORD_AUDIO and that
     * no meeting is being recorded.
     */
    public void start(@NonNull Ui ui, @NonNull ContextSource context) {
        if (isActive()) return;
        this.ui = ui;
        this.context = context;
        epoch++;
        reconnects = 0;
        pendingTurns = 0;
        clipMode = false;
        muted = false;
        setState(State.CONNECTING, null);
        final int myEpoch = epoch;
        repository.voiceConfig(result -> {
            if (myEpoch != epoch) return;
            if (!result.isSuccess() || result.data == null) {
                if (result.error != null && result.error.isUnauthorized()) {
                    stopInternal();
                    if (this.ui != null) this.ui.onVoiceUnauthorized();
                    return;
                }
                end(result.error != null ? result.error.message
                        : "Voice mode could not reach the server.");
                return;
            }
            if (!result.data.enabled) {
                end("Voice mode is switched off on this server — typing still works.");
                return;
            }
            requestFocus();
            openSocket();
        });
    }

    /** The person ended voice mode. */
    public void stop() {
        if (!isActive()) return;
        Ui current = ui;
        stopInternal();
        if (current != null) current.onVoiceEnded(null);
    }

    /** Stop Jarvis talking (the Stop button). Nothing already done is undone. */
    public void interrupt() {
        if (!isActive()) return;
        silenceLocal();
        if (socket != null && ready) socket.sendText(VoiceProtocol.control("interrupt"));
        afterSpeech();
    }

    /** A typed turn — a chip or the keyboard — in the spoken conversation. */
    public boolean sendText(@NonNull String text) {
        if (!canSendText() || socket == null) return false;
        if (text.trim().isEmpty() || text.length() > MAX_TEXT) return false;
        // A new request while Jarvis talks: stop it here AND on the server,
        // or the server keeps sending the old answer's audio.
        if (isPlaying()) {
            silenceLocal();
            socket.sendText(VoiceProtocol.control("interrupt"));
        }
        boolean sent = socket.sendText(VoiceProtocol.text(text));
        if (sent) {
            pendingTurns++;
            setState(State.THINKING, null);
        }
        return sent;
    }

    /** The screen's subject changed. */
    public void contextChanged() {
        if (socket != null && ready && context != null) {
            socket.sendText(VoiceProtocol.context(context.leadId(), context.proposalId(),
                    context.meetingId()));
        }
    }

    /** Speak with {@code voice} (the chosen avatar's) from the next sentence on. */
    public void setVoice(@Nullable String voice) {
        voiceName = voice;
        if (voice != null && socket != null && ready) {
            socket.sendText(VoiceProtocol.voice(voice));
        }
    }

    /**
     * Play a short clip here (an avatar's voice sample), as Jarvis speech:
     * anything Jarvis was saying stops, and the mic stays shut while it plays
     * unless talking over is allowed.
     */
    public void playClip(@NonNull VoicePlayer.Pcm clip) {
        interrupt();
        if (player == null) ensurePlayer();
        SpeechOutput out = player;
        if (out == null) return;
        out.setSampleRate(clip.sampleRate);
        out.play(clip.data);
        out.endOfSpeech();
        if (isActive()) setState(State.SPEAKING, null);
        updateMicGate();
    }

    public boolean isMuted() {
        return muted;
    }

    /**
     * Mute or unmute the microphone. Muting mid-sentence also throws away what
     * the server has heard so far, so half a request is never acted on.
     */
    public void setMuted(boolean value) {
        if (muted == value) return;
        muted = value;
        if (muted && socket != null && ready) socket.sendText(VoiceProtocol.control("cancel"));
        if (muted && clipInput != null && clipMode) {
            clipInput.destroy();
            clipInput = null;
            clipBusy = false;
            setState(State.PAUSED, null);
        }
        updateMicGate();
        if (!muted && clipMode && state == State.PAUSED) listenForClip();
        if (ui != null) ui.onVoiceState(state, null);
    }

    /** One-clip path: listen again after a pause. */
    public void resumeListening() {
        if (clipMode && state == State.PAUSED) listenForClip();
    }

    /** The screen is going away: end quietly. */
    public void release() {
        stopInternal();
        ui = null;
        context = null;
    }

    /**
     * Speak through {@code output} from now on (the avatar, once it is up).
     * Takes over when whatever is being said has finished. An output an echo
     * canceller cannot hear rules out talking over Jarvis, so a session that
     * allowed it is reopened without.
     */
    public void useSpeechOutput(@NonNull SpeechOutput output) {
        if (output == player) return;
        pendingOutput = output;
        if (!isPlaying()) swapOutput();
    }

    /**
     * Back to the app's own player (the avatar was hidden or failed). Whatever
     * the avatar was saying is dropped.
     */
    public void useDefaultSpeechOutput(@NonNull SpeechOutput leaving) {
        if (pendingOutput == leaving) pendingOutput = null;
        if (player != leaving) return;
        player.setListener(null);
        player.stopNow();
        player = null;
        externalOutput = false;
        if (isActive()) ensurePlayer();
        afterSpeech();
    }

    private void swapOutput() {
        SpeechOutput next = pendingOutput;
        pendingOutput = null;
        if (next == null) return;
        if (player != null) {
            player.setListener(null);
            if (externalOutput) player.stopNow();
            else player.release();
        }
        player = next;
        externalOutput = true;
        // Bound to the output, not the session: it may be attached before
        // voice mode starts, and stays attached across restarts.
        next.setListener(() -> {
            if (player == next) afterSpeech();
        });
        if (bargeIn && !next.echoCancellable() && isActive() && !clipMode && ready) {
            reconnectNow();
        }
        updateMicGate();
    }

    // ── streaming path ───────────────────────────────────────────────

    private void openSocket() {
        ready = false;
        bargeIn = prefs.bargeIn() && bargeInSupported()
                && (player == null || player.echoCancellable());
        SocketListener listener = new SocketListener(epoch);
        VoiceSocket s = new VoiceSocket(listener);
        listener.own = s;
        socket = s;
        s.connect(httpClient, VoiceProtocol.socketUrl(environment.getBaseUrl()));
    }

    private final class SocketListener implements VoiceSocket.Listener {
        private final int myEpoch;
        /** The socket this listener belongs to; a replaced one goes quiet. */
        @Nullable VoiceSocket own;

        SocketListener(int myEpoch) {
            this.myEpoch = myEpoch;
        }

        private boolean stale() {
            return myEpoch != epoch || own == null || own != socket;
        }

        @Override
        public void onOpen() {
            if (stale() || socket == null) return;
            ContextSource c = context;
            socket.sendText(VoiceProtocol.start(session.sessionId(), true, bargeIn, voiceName,
                    c == null ? null : c.leadId(),
                    c == null ? null : c.proposalId(),
                    c == null ? null : c.meetingId()));
        }

        @Override
        public void onMessage(@NonNull JsonObject message) {
            if (!stale()) handle(message);
        }

        @Override
        public void onAudio(@NonNull byte[] pcm) {
            if (stale() || player == null || dropAudio) return;
            player.play(pcm);
        }

        @Override
        public void onClosed(int code, @Nullable String reason, boolean everOpened) {
            if (!stale()) socketClosed(code, reason, everOpened);
        }
    }

    private void handle(@NonNull JsonObject m) {
        String type = VoiceProtocol.type(m);
        switch (type) {
            case "ready": {
                ready = true;
                reconnects = 0;
                bargeIn = VoiceProtocol.bool(m, "barge_in", bargeIn);
                JsonObject voice = m.has("server_voice") && m.get("server_voice").isJsonObject()
                        ? m.getAsJsonObject("server_voice") : null;
                serverVoice = voice != null && VoiceProtocol.bool(voice, "available", false);
                ensurePlayer();
                startMic();
                if (!isBusy()) setState(State.LISTENING, null);
                break;
            }
            case "server_voice":
                serverVoice = VoiceProtocol.bool(m, "ready", false)
                        || VoiceProtocol.bool(m, "available", false);
                break;
            case "speech_started":
                if (bargeIn) silenceLocal();
                setState(State.HEARING, null);
                break;
            case "speech_ended":
                pendingTurns++;
                setState(State.TRANSCRIBING, null);
                break;
            case "listening":
                // A blip with no words: if it closed a queued turn, count it.
                if (m.has("turn")) pendingTurns = Math.max(0, pendingTurns - 1);
                if (!isBusy()) setState(State.LISTENING, null);
                break;
            case "transcribing":
                setState(State.TRANSCRIBING, null);
                break;
            case "transcript": {
                String text = VoiceProtocol.string(m, "text");
                if (text != null && !text.trim().isEmpty() && ui != null) {
                    ui.onVoiceTranscript(text.trim(),
                            VoiceProtocol.bool(m, "low_confidence", false));
                }
                setState(State.THINKING, null);
                break;
            }
            case "thinking": {
                String said = VoiceProtocol.string(m, "text");
                setState(State.THINKING, said);
                // The server speaks its own acknowledgement when it has a voice.
                if (!serverVoice && said != null) speakOnDevice(said);
                break;
            }
            case "reply":
                onReply(m);
                break;
            case "speak_start": {
                dropAudio = false;
                if (player != null) {
                    player.setSampleRate(VoiceProtocol.integer(m, "sample_rate",
                            VoiceProtocol.OUTPUT_SAMPLE_RATE));
                }
                // The device voice may still be on an acknowledgement.
                if (deviceSpeaking) stopDeviceVoice();
                setState(State.SPEAKING, null);
                String said = VoiceProtocol.string(m, "text");
                if (said != null && ui != null) ui.onVoiceSpeaking(said);
                break;
            }
            case "speak_end":
                if (player != null) player.endOfSpeech();
                if (player == null || !player.isActive()) afterSpeech();
                break;
            case "interrupted":
                silenceLocal();
                afterSpeech();
                break;
            case "error":
                onServerError(m);
                break;
            default:
                // pong, context echo — nothing to show.
                break;
        }
    }

    private void onReply(@NonNull JsonObject m) {
        pendingTurns = Math.max(0, pendingTurns - 1);
        AssistantDtos.VoiceTurnResponse reply = VoiceProtocol.reply(m);
        deliver(reply);
        if ("server".equals(reply.spokenBy)) return;   // speak_start/audio/speak_end follow
        // "device" from a server that HAS a voice means the answer is stale
        // (interrupted, or a newer request is queued) — show it, don't say it.
        boolean stale = serverVoice || isBusy();
        if (!stale && reply.speech != null && !reply.speech.trim().isEmpty()) {
            speakOnDevice(reply.speech);
        } else {
            afterSpeech();
        }
    }

    private void deliver(@NonNull AssistantDtos.VoiceTurnResponse reply) {
        if (ui == null) return;
        if (!reply.acted) {
            ui.onVoiceNotActed(reply.reply == null ? "" : reply.reply, reply.transcript);
        } else {
            ui.onVoiceReply(reply);
        }
    }

    private void onServerError(@NonNull JsonObject m) {
        String code = VoiceProtocol.string(m, "code");
        String message = VoiceProtocol.string(m, "message");
        boolean fatal = VoiceProtocol.bool(m, "fatal", false);
        if (fatal) {
            // The close follows; remember why, for socketClosed.
            lastFatal = message;
            return;
        }
        // A voice the server does not have: it keeps its default. Not news.
        if ("bad_voice".equals(code)) return;
        if (m.has("turn")) pendingTurns = Math.max(0, pendingTurns - 1);
        if ("budget_exceeded".equals(code) && message == null) {
            message = "This organisation's AI budget for the month is used up.";
        }
        if (ui != null && message != null) ui.onVoiceError(message);
        if (!isBusy()) setState(State.LISTENING, null);
    }

    @Nullable private String lastFatal;

    private void socketClosed(int code, @Nullable String reason, boolean everOpened) {
        socket = null;
        ready = false;
        // The server's session is gone, and with it any turn it had queued.
        pendingTurns = 0;
        stopMic();
        silenceLocal();
        String fatal = lastFatal;
        lastFatal = null;

        if (code == VoiceProtocol.CLOSE_UNAUTHORIZED) {
            Ui current = ui;
            stopInternal();
            if (current != null) current.onVoiceUnauthorized();
            return;
        }
        if (!everOpened && reconnects == 0) {
            // The upgrade itself was refused — a proxy that does not pass
            // WebSockets. The one-clip HTTP turn works through anything.
            android.util.Log.i(TAG, "Voice socket unavailable (" + reason
                    + "); using one clip per turn");
            startClipMode();
            return;
        }
        if (!VoiceProtocol.shouldReconnect(code)) {
            end(closeMessage(code, fatal));
            return;
        }
        if (reconnects >= MAX_RECONNECTS) {
            end("Voice mode lost the connection. Tap the voice button to try again.");
            return;
        }
        long delay = Math.min(MAX_BACKOFF_MS, FIRST_BACKOFF_MS << reconnects);
        reconnects++;
        setState(State.RECONNECTING, null);
        final int myEpoch = epoch;
        main.postDelayed(() -> {
            if (myEpoch == epoch && isActive() && socket == null) openSocket();
        }, delay);
    }

    @NonNull
    private static String closeMessage(int code, @Nullable String fatal) {
        switch (code) {
            case VoiceProtocol.CLOSE_IDLE:
                return "Voice mode ended after a long silence.";
            case VoiceProtocol.CLOSE_FORBIDDEN:
                return fatal != null ? fatal : "Voice mode isn't available for this account.";
            case VoiceProtocol.CLOSE_BAD_REQUEST:
                return fatal != null ? fatal : "Voice mode could not start — please update the app.";
            default:
                return fatal != null ? fatal : "Voice mode ended.";
        }
    }

    private void reconnectNow() {
        if (socket != null) socket.close();
        socket = null;
        ready = false;
        stopMic();
        silenceLocal();
        pendingTurns = 0;
        setState(State.CONNECTING, null);
        openSocket();
    }

    private void ensurePlayer() {
        if (player != null) return;
        final int myEpoch = epoch;
        player = new VoicePlayer(() -> {
            if (myEpoch == epoch) afterSpeech();
        });
        externalOutput = false;
    }

    private void startMic() {
        if (mic != null && mic.isRunning()) return;
        if (androidx.core.content.ContextCompat.checkSelfPermission(app,
                android.Manifest.permission.RECORD_AUDIO)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            end("Microphone permission is needed for voice mode.");
            return;
        }
        MicStreamer m = new MicStreamer();
        mic = m;
        final int myEpoch = epoch;
        m.start(new MicStreamer.Sink() {
            @Override
            public void onFrame(@NonNull byte[] frame) {
                VoiceSocket s = socket;
                if (s == null || !micOpen) return;
                s.sendAudio(frame);
            }

            @Override
            public void onLevel(float level) {
                if (myEpoch == epoch && ui != null) {
                    ui.onVoiceLevel(micOpen ? level : 0f);
                }
            }

            @Override
            public void onMicError(@NonNull String message) {
                if (myEpoch == epoch) end(message);
            }
        });
        updateMicGate();
    }

    private void stopMic() {
        if (mic != null) mic.stop();
        mic = null;
        micOpen = false;
    }

    /** Read on the capture thread: are frames sent right now? */
    private volatile boolean micOpen;

    private void updateMicGate() {
        boolean playing = isPlaying();
        // Barge-in only covers the server voice: the device voice's audio is
        // not guaranteed to reach the echo canceller.
        boolean canHearOutput = player == null || player.echoCancellable();
        boolean gate = deviceSpeaking || (playing && !(bargeIn && canHearOutput));
        micOpen = ready && !clipMode && mic != null && !gate && !muted;
    }

    // ── one-clip path ────────────────────────────────────────────────

    private void startClipMode() {
        clipMode = true;
        ensurePlayer();
        listenForClip();
    }

    private void listenForClip() {
        if (!isActive() || !clipMode || clipBusy) return;
        if (muted) {
            setState(State.PAUSED, null);
            return;
        }
        if (androidx.core.content.ContextCompat.checkSelfPermission(app,
                android.Manifest.permission.RECORD_AUDIO)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            end("Microphone permission is needed for voice mode.");
            return;
        }
        if (clipInput == null) clipInput = new SpeechInput();
        clipBusy = true;
        setState(State.LISTENING, null);
        final int myEpoch = epoch;
        final boolean[] handedOver = {false};
        final String[] problem = {null};
        clipInput.startClip(app, new SpeechInput.Listener() {
            @Override
            public void onPartial(@NonNull String text) {
            }

            @Override
            public void onFinal(@NonNull String text) {
            }

            @Override
            public void onError(@NonNull String message) {
                problem[0] = message;
            }

            @Override
            public void onTranscribing() {
                handedOver[0] = true;
            }

            @Override
            public void onEnd() {
                if (myEpoch != epoch) return;
                if (handedOver[0]) return;   // the upload takes it from here
                clipBusy = false;
                // Nobody spoke (or the mic failed): wait for a tap rather
                // than listen to an empty room forever.
                setState(State.PAUSED, problem[0]);
            }
        }, clip -> {
            if (myEpoch != epoch) {
                //noinspection ResultOfMethodCallIgnored
                clip.delete();
                return;
            }
            uploadClip(clip, myEpoch);
        });
    }

    private void uploadClip(@NonNull File clip, int myEpoch) {
        setState(State.TRANSCRIBING, null);
        ContextSource c = context;
        repository.voiceTurn(clip, session.sessionId(),
                c == null ? null : c.leadId(),
                c == null ? null : c.proposalId(),
                c == null ? null : c.meetingId(),
                true, voiceName,
                result -> {
                    if (myEpoch != epoch) return;
                    clipBusy = false;
                    if (!result.isSuccess() || result.data == null) {
                        if (result.error != null && result.error.isUnauthorized()) {
                            Ui current = ui;
                            stopInternal();
                            if (current != null) current.onVoiceUnauthorized();
                            return;
                        }
                        String message = result.error != null ? result.error.message
                                : "That didn't go through.";
                        if (ui != null) ui.onVoiceError(message);
                        setState(State.PAUSED, message);
                        return;
                    }
                    AssistantDtos.VoiceTurnResponse reply = result.data;
                    if (reply.transcript != null && !reply.transcript.trim().isEmpty()
                            && ui != null) {
                        ui.onVoiceTranscript(reply.transcript.trim(), reply.lowConfidence);
                    }
                    deliver(reply);
                    speakClipReply(reply);
                });
    }

    private void speakClipReply(@NonNull AssistantDtos.VoiceTurnResponse reply) {
        VoicePlayer.Pcm pcm = null;
        if (reply.audio != null && reply.audio.base64 != null) {
            try {
                pcm = VoicePlayer.decodeWav(Base64.decode(reply.audio.base64, Base64.DEFAULT));
            } catch (IllegalArgumentException e) {
                pcm = null;
            }
        }
        if (pcm != null && player != null) {
            setState(State.SPEAKING, null);
            if (ui != null && reply.speech != null) ui.onVoiceSpeaking(reply.speech);
            player.setSampleRate(pcm.sampleRate);
            player.play(pcm.data);
            player.endOfSpeech();
        } else if (reply.speech != null && !reply.speech.trim().isEmpty()) {
            speakOnDevice(reply.speech);
        } else {
            afterSpeech();
        }
    }

    // ── speaking ─────────────────────────────────────────────────────

    private void speakOnDevice(@NonNull String text) {
        if (ui != null) ui.onVoiceSpeaking(text);
        // The avatar says it with moving lips, through its own queue.
        if (player != null && player.speakText(text)) {
            setState(State.SPEAKING, null);
            updateMicGate();
            return;
        }
        final int token = ++deviceSpeechToken;
        final int myEpoch = epoch;
        deviceSpeaking = true;
        updateMicGate();
        setState(State.SPEAKING, null);
        deviceVoice.speakNow(text, () -> {
            if (myEpoch != epoch || token != deviceSpeechToken) return;
            deviceSpeaking = false;
            afterSpeech();
        });
    }

    private void stopDeviceVoice() {
        deviceSpeechToken++;
        deviceSpeaking = false;
        deviceVoice.stop();
    }

    private boolean isPlaying() {
        return (player != null && player.isActive()) || deviceSpeaking;
    }

    /** Stop every sound this screen is making. */
    private void silenceLocal() {
        dropAudio = true;
        if (player != null) player.stopNow();
        if (deviceSpeaking) stopDeviceVoice();
        updateMicGate();
    }

    /** Playback finished (or was cut): back to listening if nothing else is due. */
    private void afterSpeech() {
        updateMicGate();
        if (!isActive()) return;
        if (isPlaying()) return;
        if (pendingOutput != null) swapOutput();
        if (clipMode) {
            if (!clipBusy) listenForClip();
            return;
        }
        if (!ready) return;
        setState(isBusy() ? State.THINKING : State.LISTENING, null);
    }

    /** A turn is still being worked on by the server. */
    private boolean isBusy() {
        return pendingTurns > 0;
    }

    // ── lifecycle ────────────────────────────────────────────────────

    private void end(@NonNull String reason) {
        Ui current = ui;
        stopInternal();
        if (current != null) current.onVoiceEnded(reason);
    }

    private void stopInternal() {
        epoch++;
        main.removeCallbacksAndMessages(null);
        if (socket != null) socket.close();
        socket = null;
        ready = false;
        stopMic();
        if (player != null) {
            player.setListener(null);
            if (externalOutput) player.stopNow();
            else player.release();
        }
        player = null;
        externalOutput = false;
        pendingOutput = null;
        if (clipInput != null) clipInput.destroy();
        clipInput = null;
        clipBusy = false;
        clipMode = false;
        if (deviceSpeaking) stopDeviceVoice();
        pendingTurns = 0;
        dropAudio = false;
        lastFatal = null;
        abandonFocus();
        setState(State.OFF, null);
    }

    private void setState(@NonNull State next, @Nullable String detail) {
        state = next;
        updateMicGate();
        if (ui != null) ui.onVoiceState(next, detail);
    }

    private void requestFocus() {
        AudioManager am = (AudioManager) app.getSystemService(Context.AUDIO_SERVICE);
        if (am == null) return;
        focusRequest = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                .setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build())
                .setOnAudioFocusChangeListener(change -> { })
                .build();
        am.requestAudioFocus(focusRequest);
    }

    private void abandonFocus() {
        AudioManager am = (AudioManager) app.getSystemService(Context.AUDIO_SERVICE);
        if (am != null && focusRequest != null) am.abandonAudioFocusRequest(focusRequest);
        focusRequest = null;
    }

    /** The person's voice-mode choices. */
    private static final class VoicePrefs {
        private static final String PREFS = "yuvipep_voice";
        private static final String KEY_BARGE_IN = "voice_barge_in";
        private final android.content.SharedPreferences prefs;

        VoicePrefs(@NonNull Context app) {
            prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        }

        /** Off by default: safe on every phone, and the Stop button always works. */
        boolean bargeIn() {
            return prefs.getBoolean(KEY_BARGE_IN, false);
        }

        void setBargeIn(boolean value) {
            prefs.edit().putBoolean(KEY_BARGE_IN, value).apply();
        }
    }
}
