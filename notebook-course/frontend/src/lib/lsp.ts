import type { ChapterCell } from './types';

export type Position = { line: number; character: number };
export type Range = { start: Position; end: Position };

export type LspDiagnostic = {
  range: Range;
  severity?: number;
  message: string;
  source?: string;
  code?: string | number;
};

export type CompletionItem = {
  label: string;
  kind?: number;
  detail?: string;
  documentation?: string | { kind: string; value: string };
  insertText?: string;
  textEdit?: { newText: string; range: Range };
};

type LspConfig = { rootUri: string; documentUri: string };
type Segment = { startLine: number; lineCount: number };
type DiagnosticListener = (diagnostics: LspDiagnostic[]) => void;
type LspStatus = 'connecting' | 'ready' | 'error';

type PendingRequest = {
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
};

function wsUrl(apiUrl: string, chapterId: string): string {
  const origin = apiUrl
    ? apiUrl.replace(/^http/, 'ws')
    : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`;
  return `${origin}/api/chapters/${encodeURIComponent(chapterId)}/lsp`;
}

export function documentationText(value: CompletionItem['documentation']): string | undefined {
  if (!value) return undefined;
  return typeof value === 'string' ? value : value.value;
}

export type HoverText = {
  text: string;
  format: 'markdown' | 'plaintext';
  range?: Range;
};

export function hoverText(result: unknown): HoverText | null {
  if (!result || typeof result !== 'object') return null;
  const value = result as { contents?: unknown; range?: Range };
  const contents = value.contents;
  if (typeof contents === 'string') {
    return { text: contents, format: 'markdown', range: value.range };
  }
  if (contents && typeof contents === 'object' && 'value' in contents) {
    const markup = contents as { kind?: unknown; language?: unknown; value: unknown };
    const text = String(markup.value);
    if (typeof markup.language === 'string') {
      return {
        text: `\`\`\`${markup.language}\n${text}\n\`\`\``,
        format: 'markdown',
        range: value.range
      };
    }
    return {
      text,
      format: markup.kind === 'plaintext' ? 'plaintext' : 'markdown',
      range: value.range
    };
  }
  if (Array.isArray(contents)) {
    const parts = contents.map((item) => {
      if (typeof item === 'string') return { text: item, format: 'markdown' as const };
      if (!item || typeof item !== 'object' || !('value' in item)) return null;
      const markup = item as { kind?: unknown; language?: unknown; value: unknown };
      const text = String(markup.value);
      if (typeof markup.language === 'string') {
        return { text: `\`\`\`${markup.language}\n${text}\n\`\`\``, format: 'markdown' as const };
      }
      return { text, format: markup.kind === 'plaintext' ? 'plaintext' as const : 'markdown' as const };
    }).filter((part): part is { text: string; format: 'markdown' | 'plaintext' } => Boolean(part?.text));
    if (!parts.length) return null;
    return {
      text: parts.map((part) => part.text).join('\n\n'),
      format: parts.every((part) => part.format === 'plaintext') ? 'plaintext' : 'markdown',
      range: value.range
    };
  }
  return null;
}

export function completionItems(result: unknown): CompletionItem[] {
  return Array.isArray(result) ? result : ((result as { items?: CompletionItem[] } | null)?.items ?? []);
}

export class PyrightClient {
  private socket: WebSocket | null = null;
  private config: LspConfig | null = null;
  private nextId = 0;
  private pending = new Map<number, PendingRequest>();
  private diagnostics = new Map<string, LspDiagnostic[]>();
  private listeners = new Map<string, Set<DiagnosticListener>>();
  private cellSources = new Map<string, string>();
  private cellOrder: string[] = [];
  private segments = new Map<string, Segment>();
  private documentText = '';
  private documentVersion = 1;
  private changeTimer: ReturnType<typeof setTimeout> | null = null;
  private closing = false;

  constructor(
    private apiUrl: string,
    private chapterId: string,
    private statusChanged: (status: LspStatus) => void = () => {}
  ) {}

  async connect(cells: ChapterCell[]): Promise<void> {
    this.statusChanged('connecting');
    const socket = new WebSocket(wsUrl(this.apiUrl, this.chapterId));
    this.socket = socket;

    const configPromise = new Promise<LspConfig>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('等待 Pyright 配置超时')), 8000);
      socket.onmessage = (event) => {
        const message = JSON.parse(String(event.data));
        if (message.method === 'pushthrough/config') {
          clearTimeout(timeout);
          this.config = message.params;
          resolve(message.params);
          return;
        }
        this.receive(message);
      };
    });

    await new Promise<void>((resolve, reject) => {
      socket.onopen = () => resolve();
      socket.onerror = () => reject(new Error('无法连接 Pyright 语言服务'));
      socket.onclose = () => {
        if (!this.closing) this.statusChanged('error');
      };
    });
    const config = await configPromise;

    await this.request('initialize', {
      processId: null,
      clientInfo: { name: 'Pushthrough', version: '0.1.0' },
      rootUri: config.rootUri,
      workspaceFolders: [{ uri: config.rootUri, name: this.chapterId }],
      capabilities: {
        workspace: { configuration: true, workspaceFolders: true },
        textDocument: {
          synchronization: { didSave: false },
          publishDiagnostics: { relatedInformation: true, versionSupport: true },
          completion: {
            contextSupport: true,
            completionItem: {
              snippetSupport: false,
              documentationFormat: ['markdown', 'plaintext'],
              labelDetailsSupport: true
            }
          },
          hover: { contentFormat: ['markdown', 'plaintext'] }
        }
      }
    });
    this.notify('initialized', {});
    this.notify('workspace/didChangeConfiguration', { settings: null });

    for (const cell of cells.filter((candidate) => candidate.cell_type === 'code')) {
      this.cellOrder.push(cell.id);
      this.cellSources.set(cell.id, cell.source);
    }
    this.rebuildDocument();
    this.notify('textDocument/didOpen', {
      textDocument: {
        uri: config.documentUri,
        languageId: 'python',
        version: this.documentVersion,
        text: this.documentText
      }
    });
    this.statusChanged('ready');
  }

  hasCell(cellId: string): boolean {
    return this.cellSources.has(cellId);
  }

  changeDocument(cellId: string, text: string): void {
    if (!this.cellSources.has(cellId) || this.cellSources.get(cellId) === text) return;
    this.cellSources.set(cellId, text);
    if (this.changeTimer) clearTimeout(this.changeTimer);
    this.changeTimer = setTimeout(() => this.flushDocument(), 180);
  }

  private rebuildDocument(): void {
    let combined = '';
    this.segments.clear();
    for (const [index, cellId] of this.cellOrder.entries()) {
      if (index) combined += '\n\n';
      combined += `# %% [${cellId}]\n`;
      const startLine = (combined.match(/\n/g) ?? []).length;
      const source = this.cellSources.get(cellId) ?? '';
      const lineCount = source.split('\n').length;
      this.segments.set(cellId, { startLine, lineCount });
      combined += source;
    }
    this.documentText = combined;
  }

  private flushDocument(): void {
    if (this.changeTimer) clearTimeout(this.changeTimer);
    this.changeTimer = null;
    if (!this.config) return;
    this.rebuildDocument();
    this.documentVersion += 1;
    this.notify('textDocument/didChange', {
      textDocument: { uri: this.config.documentUri, version: this.documentVersion },
      contentChanges: [{ text: this.documentText }]
    });
  }

  async completion(cellId: string, position: Position, triggerCharacter?: string): Promise<unknown> {
    this.flushDocument();
    const segment = this.segments.get(cellId);
    if (!segment || !this.config) return null;
    return this.request('textDocument/completion', {
      textDocument: { uri: this.config.documentUri },
      position: { line: segment.startLine + position.line, character: position.character },
      context: triggerCharacter ? { triggerKind: 2, triggerCharacter } : { triggerKind: 1 }
    });
  }

  async hover(cellId: string, position: Position): Promise<unknown> {
    this.flushDocument();
    const segment = this.segments.get(cellId);
    if (!segment || !this.config) return null;
    const result = await this.request('textDocument/hover', {
      textDocument: { uri: this.config.documentUri },
      position: { line: segment.startLine + position.line, character: position.character }
    });
    if (result && typeof result === 'object' && (result as { range?: Range }).range) {
      const range = (result as { range: Range }).range;
      return {
        ...(result as object),
        range: {
          start: { ...range.start, line: range.start.line - segment.startLine },
          end: { ...range.end, line: range.end.line - segment.startLine }
        }
      };
    }
    return result;
  }

  subscribeDiagnostics(cellId: string, listener: DiagnosticListener): () => void {
    const listeners = this.listeners.get(cellId) ?? new Set<DiagnosticListener>();
    listeners.add(listener);
    this.listeners.set(cellId, listeners);
    listener(this.diagnostics.get(cellId) ?? []);
    return () => {
      listeners.delete(listener);
      if (!listeners.size) this.listeners.delete(cellId);
    };
  }

  close(): void {
    this.closing = true;
    if (this.changeTimer) clearTimeout(this.changeTimer);
    this.changeTimer = null;
    if (this.config && this.socket?.readyState === WebSocket.OPEN) {
      this.notify('textDocument/didClose', { textDocument: { uri: this.config.documentUri } });
    }
    this.socket?.close();
    this.socket = null;
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(new Error('Pyright 语言服务已关闭'));
    }
    this.pending.clear();
  }

  private request(method: string, params: unknown): Promise<unknown> {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`Pyright 请求超时：${method}`));
      }, 10000);
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.send({ jsonrpc: '2.0', id, method, params });
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(error);
      }
    });
  }

  private notify(method: string, params: unknown): void {
    this.send({ jsonrpc: '2.0', method, params });
  }

  private send(message: unknown): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) throw new Error('Pyright WebSocket 尚未连接');
    this.socket.send(JSON.stringify(message));
  }

  private receive(message: any): void {
    if ('id' in message && !('method' in message)) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      clearTimeout(pending.timer);
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message ?? 'Pyright 请求失败'));
      else pending.resolve(message.result);
      return;
    }
    if (message.method === 'textDocument/publishDiagnostics' && message.params.uri === this.config?.documentUri) {
      const byCell = new Map<string, LspDiagnostic[]>();
      for (const cellId of this.cellOrder) byCell.set(cellId, []);
      for (const diagnostic of (message.params.diagnostics ?? []) as LspDiagnostic[]) {
        for (const [cellId, segment] of this.segments) {
          if (diagnostic.range.start.line < segment.startLine || diagnostic.range.start.line >= segment.startLine + segment.lineCount) continue;
          byCell.get(cellId)!.push({
            ...diagnostic,
            range: {
              start: { ...diagnostic.range.start, line: diagnostic.range.start.line - segment.startLine },
              end: { ...diagnostic.range.end, line: Math.max(0, diagnostic.range.end.line - segment.startLine) }
            }
          });
          break;
        }
      }
      for (const [cellId, diagnostics] of byCell) {
        this.diagnostics.set(cellId, diagnostics);
        for (const listener of this.listeners.get(cellId) ?? []) listener(diagnostics);
      }
      return;
    }
    if ('id' in message && 'method' in message) this.send({ jsonrpc: '2.0', id: message.id, result: null });
  }
}
