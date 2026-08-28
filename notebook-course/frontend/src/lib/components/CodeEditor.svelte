<script module lang="ts">
  let nextModelId = 0;

  function createModelId() {
    nextModelId += 1;
    return `model-${nextModelId}`;
  }
</script>

<script lang="ts">
  import { onMount } from 'svelte';
  import type * as Monaco from 'monaco-editor';

  import { bindMonacoLsp } from '$lib/monaco-lsp';
  import type { PyrightClient } from '$lib/lsp';

  export let value: string;
  export let readonly = false;
  export let onchange: (value: string) => void = () => {};
  export let lspClient: PyrightClient | null = null;
  export let lspCellId: string | null = null;

  type MonacoApi = typeof import('monaco-editor');

  let container: HTMLDivElement;
  let editor: Monaco.editor.IStandaloneCodeEditor | undefined;
  let model: Monaco.editor.ITextModel | undefined;
  let monacoApi: MonacoApi | undefined;
  let disposeLsp = () => {};
  let boundClient: PyrightClient | null = null;
  let boundCellId: string | null = null;
  let syncingExternalValue = false;
  let ready = false;
  let loadError = '';

  function bindLanguageService() {
    if (!monacoApi || !model) return;
    if (boundClient === lspClient && boundCellId === lspCellId) return;
    disposeLsp();
    disposeLsp = () => {};
    boundClient = lspClient;
    boundCellId = lspCellId;
    if (lspClient && lspCellId) disposeLsp = bindMonacoLsp(monacoApi, model, lspClient, lspCellId);
  }

  function fitEditorHeight() {
    if (!editor || !container) return;
    const nextHeight = Math.max(132, Math.min(720, editor.getContentHeight()));
    if (container.style.height !== `${nextHeight}px`) {
      container.style.height = `${nextHeight}px`;
      editor.layout({ width: container.clientWidth, height: nextHeight });
    }
  }

  onMount(() => {
    let cancelled = false;
    let disposeEditor = () => {};

    void (async () => {
      const workerModule = await import('monaco-editor/editor/editor.worker?worker');
      const scope = self as typeof self & {
        MonacoEnvironment?: { getWorker: () => Worker };
      };
      scope.MonacoEnvironment ??= { getWorker: () => new workerModule.default() };

      const monaco = await import('monaco-editor');
      if (cancelled) return;
      monacoApi = monaco;

      monaco.editor.defineTheme('pushthrough-light', {
        base: 'vs',
        inherit: true,
        colors: {
          'editor.background': '#FFFFFF',
          'editor.foreground': '#263238',
          'editorCursor.foreground': '#537B2C',
          'editor.selectionBackground': '#BBD98A',
          'editor.inactiveSelectionBackground': '#D7E7BC',
          'editor.selectionHighlightBackground': '#E7F0D8',
          'editor.lineHighlightBackground': '#F2F6EC',
          'editor.lineHighlightBorder': '#00000000',
          'editorGutter.background': '#F7F7F3',
          'editorLineNumber.foreground': '#9AA097',
          'editorLineNumber.activeForeground': '#5D6D50',
          'editorIndentGuide.background1': '#E5E8E0',
          'editorIndentGuide.activeBackground1': '#BAC6AF',
          'editorBracketMatch.background': '#E7EFD9',
          'editorBracketMatch.border': '#B7C99C',
          'editorError.foreground': '#C4473A',
          'editorWarning.foreground': '#C08216',
          'editorInfo.foreground': '#3979A8',
          'editorHint.foreground': '#6B8F45',
          'editorWidget.background': '#FFFFFF',
          'editorWidget.border': '#D6D9D0',
          'editorSuggestWidget.background': '#FFFFFF',
          'editorSuggestWidget.border': '#D6D9D0',
          'editorSuggestWidget.foreground': '#263238',
          'editorSuggestWidget.highlightForeground': '#3F7622',
          'editorSuggestWidget.selectedBackground': '#263A1F',
          'editorSuggestWidget.selectedForeground': '#FFFFFF',
          'editorSuggestWidget.selectedIconForeground': '#C9F36B',
          'editorSuggestWidget.focusHighlightForeground': '#D8FF80',
          'editorHoverWidget.background': '#FFFFFF',
          'editorHoverWidget.border': '#D6D9D0'
        },
        rules: [
          { token: 'keyword', foreground: '6D3CCF' },
          { token: 'identifier', foreground: '263238' },
          { token: 'type.identifier', foreground: '176B63' },
          { token: 'string', foreground: '9A3F32' },
          { token: 'number', foreground: 'A14F00' },
          { token: 'comment', foreground: '71806A', fontStyle: 'italic' },
          { token: 'operator', foreground: '59635A' },
          { token: 'delimiter', foreground: '59635A' }
        ]
      });

      const uri = monaco.Uri.parse(
        `inmemory://pushthrough/${encodeURIComponent(lspCellId ?? 'scratch')}/${createModelId()}.py`
      );
      model = monaco.editor.createModel(value, 'python', uri);
      model.detectIndentation(false, 4);
      model.updateOptions({ tabSize: 4, indentSize: 4, insertSpaces: true });

      editor = monaco.editor.create(container, {
        model,
        theme: 'pushthrough-light',
        readOnly: readonly,
        ariaLabel: lspCellId ? `Python Code Cell ${lspCellId}` : 'Python Code Cell',
        automaticLayout: true,
        autoIndent: 'full',
        autoClosingBrackets: 'languageDefined',
        autoClosingQuotes: 'languageDefined',
        bracketPairColorization: { enabled: true },
        contextmenu: true,
        cursorBlinking: 'smooth',
        cursorSmoothCaretAnimation: 'on',
        fixedOverflowWidgets: true,
        folding: true,
        fontFamily: 'JetBrains Mono, SFMono-Regular, Consolas, monospace',
        fontLigatures: true,
        fontSize: 14,
        glyphMargin: false,
        guides: { indentation: true, bracketPairs: true },
        hover: { enabled: 'on', delay: 250, sticky: true },
        lineDecorationsWidth: 10,
        lineHeight: 22,
        lineNumbers: 'on',
        lineNumbersMinChars: 3,
        links: true,
        matchBrackets: 'always',
        minimap: { enabled: false },
        mouseWheelZoom: true,
        multiCursorModifier: 'alt',
        occurrencesHighlight: 'singleFile',
        overviewRulerBorder: false,
        overviewRulerLanes: 0,
        padding: { top: 16, bottom: 16 },
        quickSuggestions: { other: true, comments: false, strings: false },
        renderLineHighlight: 'all',
        renderValidationDecorations: 'on',
        roundedSelection: true,
        scrollBeyondLastLine: false,
        selectionHighlight: true,
        showFoldingControls: 'mouseover',
        smoothScrolling: true,
        stickyScroll: { enabled: false },
        suggestOnTriggerCharacters: true,
        tabCompletion: 'on',
        wordBasedSuggestions: 'off',
        wordWrap: 'on',
        wrappingIndent: 'indent',
        scrollbar: {
          alwaysConsumeMouseWheel: false,
          horizontal: 'auto',
          horizontalScrollbarSize: 10,
          vertical: 'auto',
          verticalScrollbarSize: 10
        }
      });

      const contentListener = editor.onDidChangeModelContent(() => {
        fitEditorHeight();
        if (syncingExternalValue || !model) return;
        const source = model.getValue();
        onchange(source);
        if (lspClient && lspCellId) lspClient.changeDocument(lspCellId, source);
      });
      const sizeListener = editor.onDidContentSizeChange(fitEditorHeight);

      bindLanguageService();
      fitEditorHeight();
      ready = true;

      disposeEditor = () => {
        disposeLsp();
        contentListener.dispose();
        sizeListener.dispose();
        editor?.dispose();
        model?.dispose();
        editor = undefined;
        model = undefined;
      };
      if (cancelled) disposeEditor();
    })().catch((error) => {
      console.error('Monaco editor failed to load', error);
      loadError = '编辑器加载失败，请刷新页面重试。';
    });

    return () => {
      cancelled = true;
      disposeEditor();
    };
  });

  $: if (editor) editor.updateOptions({ readOnly: readonly });

  $: if (model && value !== model.getValue()) {
    syncingExternalValue = true;
    model.setValue(value);
    syncingExternalValue = false;
    if (lspClient && lspCellId) lspClient.changeDocument(lspCellId, value);
  }

  $: if (monacoApi && model) bindLanguageService();
</script>

<div class="editor-shell">
  <div class="editor" bind:this={container}></div>
  {#if !ready}
    <div class:error={Boolean(loadError)} class="editor-state">{loadError || '正在加载编辑器…'}</div>
  {/if}
</div>

<style>
  .editor-shell {
    position: relative;
    min-height: 132px;
    overflow: visible;
    background: #fff;
  }
  .editor {
    width: 100%;
    height: 132px;
    min-height: 132px;
  }
  .editor-state {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    color: #899084;
    background: #fff;
    font-size: 13px;
  }
  .editor-state.error {
    color: #a84d45;
  }
  :global(.monaco-editor),
  :global(.monaco-editor .overflow-guard),
  :global(.monaco-editor .monaco-scrollable-element) {
    border-radius: 0;
  }
  :global(.monaco-editor .suggest-widget),
  :global(.monaco-editor .monaco-hover) {
    border-radius: 8px;
    box-shadow: 0 10px 30px rgba(27, 33, 24, .2);
  }
  :global(.monaco-editor .monaco-hover-content) {
    max-width: min(620px, 75vw);
  }
</style>
