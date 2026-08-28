import type * as Monaco from 'monaco-editor';

import {
  completionItems,
  documentationText,
  hoverText,
  type LspDiagnostic,
  type Position,
  type PyrightClient,
  type Range
} from './lsp';

type MonacoApi = typeof import('monaco-editor');

const completionKinds: Record<number, Monaco.languages.CompletionItemKind> = {
  1: 18,  // Text
  2: 0,   // Method
  3: 1,   // Function
  4: 2,   // Constructor
  5: 3,   // Field
  6: 4,   // Variable
  7: 5,   // Class
  8: 7,   // Interface
  9: 8,   // Module
  10: 9,  // Property
  11: 12, // Unit
  12: 13, // Value
  13: 15, // Enum
  14: 17, // Keyword
  15: 27, // Snippet
  16: 19, // Color
  17: 20, // File
  18: 21, // Reference
  19: 23, // Folder
  20: 16, // EnumMember
  21: 14, // Constant
  22: 6,  // Struct
  23: 10, // Event
  24: 11, // Operator
  25: 24  // TypeParameter
};

function lspPosition(position: Monaco.Position): Position {
  return { line: position.lineNumber - 1, character: position.column - 1 };
}

function modelPosition(model: Monaco.editor.ITextModel, position: Position): Monaco.IPosition {
  const lineNumber = Math.min(Math.max(position.line + 1, 1), model.getLineCount());
  const column = Math.min(Math.max(position.character + 1, 1), model.getLineMaxColumn(lineNumber));
  return { lineNumber, column };
}

function modelRange(monaco: MonacoApi, model: Monaco.editor.ITextModel, range: Range): Monaco.Range {
  const start = modelPosition(model, range.start);
  const end = modelPosition(model, range.end);
  return new monaco.Range(start.lineNumber, start.column, end.lineNumber, end.column);
}

function markerSeverity(monaco: MonacoApi, severity?: number): Monaco.MarkerSeverity {
  if (severity === 1) return monaco.MarkerSeverity.Error;
  if (severity === 2) return monaco.MarkerSeverity.Warning;
  if (severity === 3) return monaco.MarkerSeverity.Info;
  return monaco.MarkerSeverity.Hint;
}

function markers(
  monaco: MonacoApi,
  model: Monaco.editor.ITextModel,
  diagnostics: LspDiagnostic[]
): Monaco.editor.IMarkerData[] {
  return diagnostics.map((diagnostic) => {
    const range = modelRange(monaco, model, diagnostic.range);
    return {
      startLineNumber: range.startLineNumber,
      startColumn: range.startColumn,
      endLineNumber: range.endLineNumber,
      endColumn: range.endColumn,
      severity: markerSeverity(monaco, diagnostic.severity),
      message: diagnostic.message,
      source: diagnostic.source ?? 'Pyright',
      code: diagnostic.code === undefined ? undefined : String(diagnostic.code)
    };
  });
}

function markdown(monaco: MonacoApi, value: string, format: 'markdown' | 'plaintext'): Monaco.IMarkdownString {
  const escapedPlaintext = value.replace(/[\\`*_{}[\]()#+\-.!<>|]/g, '\\$&');
  return {
    value: format === 'markdown' ? value : escapedPlaintext,
    isTrusted: false,
    supportHtml: false
  };
}

export function bindMonacoLsp(
  monaco: MonacoApi,
  model: Monaco.editor.ITextModel,
  client: PyrightClient,
  cellId: string
): () => void {
  const markerOwner = `pyright:${cellId}`;

  const completionProvider = monaco.languages.registerCompletionItemProvider('python', {
    triggerCharacters: ['.'],
    async provideCompletionItems(candidateModel, position, context) {
      if (candidateModel !== model || model.isDisposed()) return { suggestions: [] };
      try {
        const triggerCharacter = context.triggerKind === monaco.languages.CompletionTriggerKind.TriggerCharacter
          ? context.triggerCharacter
          : undefined;
        const result = await client.completion(cellId, lspPosition(position), triggerCharacter);
        const word = model.getWordUntilPosition(position);
        const range = new monaco.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn);
        return {
          suggestions: completionItems(result).map((item) => ({
            label: item.label,
            kind: completionKinds[item.kind ?? 0] ?? monaco.languages.CompletionItemKind.Text,
            detail: item.detail,
            documentation: documentationText(item.documentation),
            insertText: item.textEdit?.newText ?? item.insertText ?? item.label,
            range
          }))
        };
      } catch {
        return { suggestions: [] };
      }
    }
  });

  const hoverProvider = monaco.languages.registerHoverProvider('python', {
    async provideHover(candidateModel, position) {
      if (candidateModel !== model || model.isDisposed()) return null;
      try {
        const result = hoverText(await client.hover(cellId, lspPosition(position)));
        if (!result?.text) return null;
        return {
          range: result.range ? modelRange(monaco, model, result.range) : undefined,
          contents: [markdown(monaco, result.text, result.format)]
        };
      } catch {
        return null;
      }
    }
  });

  const unsubscribeDiagnostics = client.subscribeDiagnostics(cellId, (diagnostics) => {
    if (!model.isDisposed()) monaco.editor.setModelMarkers(model, markerOwner, markers(monaco, model, diagnostics));
  });

  return () => {
    unsubscribeDiagnostics();
    completionProvider.dispose();
    hoverProvider.dispose();
    if (!model.isDisposed()) monaco.editor.setModelMarkers(model, markerOwner, []);
  };
}
