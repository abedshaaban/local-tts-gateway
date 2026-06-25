export type GatewayEvent = {
  type: string;
  [key: string]: unknown;
};

export type ConversationOptions = {
  baseUrl?: string;
  reconnect?: boolean;
  reconnectDelayMs?: number;
  maxReconnectAttempts?: number;
  bargeIn?: boolean;
  inputSampleRate?: number;
  outputSampleRate?: number;
  voice?: string;
  speed?: number;
  onEvent?: (event: GatewayEvent) => void;
  onAudio?: (audio: ArrayBuffer) => void;
};

function websocketUrl(baseUrl: string, path: string): string {
  const url = new URL(path, baseUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function downsampleToPCM16(
  input: Float32Array,
  inputRate: number,
  outputRate: number,
): ArrayBuffer {
  const ratio = inputRate / outputRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Int16Array(outputLength);
  for (let index = 0; index < outputLength; index += 1) {
    const start = Math.floor(index * ratio);
    const end = Math.min(input.length, Math.floor((index + 1) * ratio));
    let sum = 0;
    for (let source = start; source < end; source += 1) {
      sum += input[source];
    }
    const sample = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    output[index] = sample < 0 ? sample * 32768 : sample * 32767;
  }
  return output.buffer;
}

export class PCMPlayer {
  private context: AudioContext;
  private nextStartTime = 0;
  private sources = new Set<AudioBufferSourceNode>();

  constructor(sampleRate = 24000) {
    this.context = new AudioContext({ sampleRate });
  }

  async playFloat32LE(data: ArrayBuffer, sampleRate = 24000): Promise<void> {
    await this.context.resume();
    const copied = data.slice(0);
    const samples = new Float32Array(copied);
    const buffer = this.context.createBuffer(1, samples.length, sampleRate);
    buffer.copyToChannel(samples, 0);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    const startAt = Math.max(this.context.currentTime, this.nextStartTime);
    source.start(startAt);
    this.nextStartTime = startAt + buffer.duration;
    this.sources.add(source);
    source.onended = () => this.sources.delete(source);
  }

  stop(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // The source may have already ended.
      }
    }
    this.sources.clear();
    this.nextStartTime = this.context.currentTime;
  }
}

export class ConversationClient {
  private options: Required<
    Pick<
      ConversationOptions,
      | "baseUrl"
      | "reconnect"
      | "reconnectDelayMs"
      | "maxReconnectAttempts"
      | "bargeIn"
      | "inputSampleRate"
      | "outputSampleRate"
    >
  > &
    ConversationOptions;
  private socket?: WebSocket;
  private reconnectAttempts = 0;
  private manuallyClosed = false;
  private microphoneContext?: AudioContext;
  private microphoneStream?: MediaStream;
  private microphoneNode?: ScriptProcessorNode;
  readonly player?: PCMPlayer;

  constructor(options: ConversationOptions = {}) {
    this.options = {
      baseUrl: options.baseUrl ?? "http://127.0.0.1:47829",
      reconnect: options.reconnect ?? true,
      reconnectDelayMs: options.reconnectDelayMs ?? 750,
      maxReconnectAttempts: options.maxReconnectAttempts ?? 5,
      bargeIn: options.bargeIn ?? true,
      inputSampleRate: options.inputSampleRate ?? 16000,
      outputSampleRate: options.outputSampleRate ?? 24000,
      ...options,
    };
    this.player =
      typeof AudioContext === "undefined"
        ? undefined
        : new PCMPlayer(this.options.outputSampleRate);
  }

  async connect(): Promise<void> {
    this.manuallyClosed = false;
    const url = websocketUrl(this.options.baseUrl, "/ws/conversation");
    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(url);
      socket.binaryType = "arraybuffer";
      this.socket = socket;
      socket.onopen = () => {
        this.reconnectAttempts = 0;
        this.send({
          type: "session.start",
          config: {
            format: "pcm_s16le",
            sample_rate: this.options.inputSampleRate,
            channels: 1,
            barge_in: this.options.bargeIn,
            voice: this.options.voice,
            speed: this.options.speed,
          },
        });
        resolve();
      };
      socket.onerror = () => reject(new Error("Conversation WebSocket failed."));
      socket.onmessage = (message) => {
        if (message.data instanceof ArrayBuffer) {
          this.options.onAudio?.(message.data);
          void this.player?.playFloat32LE(
            message.data,
            this.options.outputSampleRate,
          );
          return;
        }
        const event = JSON.parse(String(message.data)) as GatewayEvent;
        if (
          event.type === "response.interrupted" ||
          event.type === "response.cancelled"
        ) {
          this.player?.stop();
        }
        this.options.onEvent?.(event);
      };
      socket.onclose = () => {
        if (
          !this.manuallyClosed &&
          this.options.reconnect &&
          this.reconnectAttempts < this.options.maxReconnectAttempts
        ) {
          this.reconnectAttempts += 1;
          globalThis.setTimeout(
            () => void this.connect(),
            this.options.reconnectDelayMs,
          );
        }
      };
    });
  }

  send(event: GatewayEvent): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("Conversation WebSocket is not connected.");
    }
    this.socket.send(JSON.stringify(event));
  }

  sendAudio(pcmS16LE: ArrayBuffer): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("Conversation WebSocket is not connected.");
    }
    this.socket.send(pcmS16LE);
  }

  createResponse(text: string, responseId?: string): void {
    this.send({ type: "response.create", text, response_id: responseId });
  }

  startResponse(responseId?: string): void {
    this.send({ type: "response.start", response_id: responseId });
  }

  appendResponseText(text: string): void {
    this.send({ type: "response.text.delta", text });
  }

  finishResponse(): void {
    this.send({ type: "response.text.done" });
  }

  cancelResponse(): void {
    this.send({ type: "response.cancel" });
    this.player?.stop();
  }

  commitAudio(): void {
    this.send({ type: "input_audio_buffer.commit" });
  }

  async startMicrophone(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone capture is not available.");
    }
    this.microphoneStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    this.microphoneContext = new AudioContext();
    const source = this.microphoneContext.createMediaStreamSource(
      this.microphoneStream,
    );
    this.microphoneNode = this.microphoneContext.createScriptProcessor(
      4096,
      1,
      1,
    );
    this.microphoneNode.onaudioprocess = (event) => {
      if (this.socket?.readyState !== WebSocket.OPEN) return;
      const samples = event.inputBuffer.getChannelData(0);
      this.sendAudio(
        downsampleToPCM16(
          samples,
          this.microphoneContext!.sampleRate,
          this.options.inputSampleRate,
        ),
      );
    };
    source.connect(this.microphoneNode);
    this.microphoneNode.connect(this.microphoneContext.destination);
  }

  async stopMicrophone(): Promise<void> {
    this.microphoneNode?.disconnect();
    this.microphoneNode = undefined;
    for (const track of this.microphoneStream?.getTracks() ?? []) {
      track.stop();
    }
    this.microphoneStream = undefined;
    await this.microphoneContext?.close();
    this.microphoneContext = undefined;
  }

  async close(): Promise<void> {
    this.manuallyClosed = true;
    await this.stopMicrophone();
    this.player?.stop();
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.send({ type: "session.end" });
    }
    this.socket?.close();
    this.socket = undefined;
  }
}

export class LocalTTSGateway {
  constructor(readonly baseUrl = "http://127.0.0.1:47829") {}

  async speech(
    input: string,
    options: {
      voice?: string;
      responseFormat?: "mp3" | "opus" | "aac" | "flac" | "wav" | "pcm";
      speed?: number;
    } = {},
  ): Promise<ArrayBuffer> {
    const response = await fetch(new URL("/v1/audio/speech", this.baseUrl), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "local-tts",
        input,
        voice: options.voice ?? "alloy",
        response_format: options.responseFormat ?? "wav",
        speed: options.speed ?? 1,
      }),
    });
    if (!response.ok) throw new Error(await response.text());
    return response.arrayBuffer();
  }

  async transcribe(
    audio: Blob,
    options: { filename?: string; responseFormat?: "json" | "text" } = {},
  ): Promise<{ text: string }> {
    const form = new FormData();
    form.append("file", audio, options.filename ?? "audio.webm");
    form.append("model", "local-stt");
    form.append("response_format", options.responseFormat ?? "json");
    const response = await fetch(
      new URL("/v1/audio/transcriptions", this.baseUrl),
      { method: "POST", body: form },
    );
    if (!response.ok) throw new Error(await response.text());
    if (options.responseFormat === "text") {
      return { text: await response.text() };
    }
    return response.json() as Promise<{ text: string }>;
  }

  conversation(options: ConversationOptions = {}): ConversationClient {
    return new ConversationClient({ baseUrl: this.baseUrl, ...options });
  }
}
