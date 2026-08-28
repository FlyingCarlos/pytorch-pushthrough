<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { page } from '$app/stores';
  import { marked } from 'marked';
  import CodeEditor from '$lib/components/CodeEditor.svelte';
  import CellOutput from '$lib/components/CellOutput.svelte';
  import TestResult from '$lib/components/TestResult.svelte';
  import { PyrightClient } from '$lib/lsp';
  import type { Chapter, ChapterCell, NotebookOutput, TestResult as TestResultType } from '$lib/types';

  const API_URL = import.meta.env.VITE_API_URL ?? '';
  let chapterId = '';

  let chapter: Chapter | null = null;
  let sources: Record<string, string> = {};
  let outputs: Record<string, NotebookOutput[]> = {};
  let testResults: Record<string, TestResultType | null> = {};
  let running: Record<string, boolean> = {};
  let runningThrough: string | null = null;
  let resetting: Record<string, boolean> = {};
  let resettingChapter = false;
  let loading = true;
  let pageError = '';
  let navOpen = true;
  let lspClient: PyrightClient | null = null;
  let lspStatus: 'connecting' | 'ready' | 'error' = 'connecting';

  onMount(() => {
    chapterId = $page.params.chapterId ?? '';
    navOpen = window.innerWidth >= 760;
    loadChapter();
  });

  onDestroy(() => lspClient?.close());

  async function loadChapter() {
    loading = true;
    pageError = '';
    try {
      const response = await fetch(`${API_URL}/api/chapters/${chapterId}`);
      if (!response.ok) throw new Error(await response.text());
      chapter = await response.json();
      sources = Object.fromEntries(chapter!.cells.map((cell) => [cell.id, cell.source]));
      testResults = Object.fromEntries(
        chapter!.cells.map((cell) => [cell.id, chapter!.progress[cell.id]?.test_result ?? null])
      );
      lspClient?.close();
      const nextLspClient = new PyrightClient(API_URL, chapterId, (status) => lspStatus = status);
      lspStatus = 'connecting';
      try {
        await nextLspClient.connect(chapter!.cells);
        lspClient = nextLspClient;
        lspStatus = 'ready';
      } catch (error) {
        console.error('Pyright language service failed to start', error);
        nextLspClient.close();
        lspClient = null;
        lspStatus = 'error';
      }
    } catch (error) {
      pageError = error instanceof Error ? error.message : String(error);
    } finally {
      loading = false;
    }
  }

  function markdown(source: string): string {
    return String(marked.parse(source));
  }

  function updateSource(cellId: string, source: string) {
    sources = { ...sources, [cellId]: source };
    if (chapter && chapter.progress[cellId]?.status === 'passed') {
      chapter.progress[cellId] = { ...chapter.progress[cellId], status: 'dirty' };
      chapter = { ...chapter };
    }
  }

  function prerequisiteIsMissing(cell: ChapterCell): boolean {
    if (!chapter || !cell.depends_on.length) return false;
    const statusByExercise = Object.fromEntries(
      chapter.cells
        .filter((candidate) => candidate.exercise_id)
        .map((candidate) => [candidate.exercise_id, chapter!.progress[candidate.id]?.status])
    );
    return cell.depends_on.some((dependency) => statusByExercise[dependency] !== 'passed');
  }

  async function runCell(cell: ChapterCell, check: boolean) {
    if (!chapter) return;
    running = { ...running, [cell.id]: true };
    outputs = { ...outputs, [cell.id]: [] };
    testResults = { ...testResults, [cell.id]: null };
    try {
      const response = await fetch(`${API_URL}/api/chapters/${chapterId}/cells/${cell.id}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source: sources[cell.id], check })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? '运行失败');
      outputs = { ...outputs, [cell.id]: result.outputs ?? [] };
      testResults = { ...testResults, [cell.id]: result.test_result ?? null };
      chapter.progress = result.progress;
      chapter = { ...chapter };
    } catch (error) {
      outputs = {
        ...outputs,
        [cell.id]: [
          {
            output_type: 'error',
            ename: 'RequestError',
            evalue: error instanceof Error ? error.message : String(error)
          }
        ]
      };
    } finally {
      running = { ...running, [cell.id]: false };
    }
  }

  async function runThrough(cell: ChapterCell) {
    if (!chapter || runningThrough) return;
    const targetIndex = chapter.cells.findIndex((candidate) => candidate.id === cell.id);
    const cellsToRun = chapter.cells.filter(
      (candidate, index) => index <= targetIndex && candidate.cell_type === 'code' && candidate.editable
    );
    runningThrough = cell.id;
    running = {
      ...running,
      ...Object.fromEntries(cellsToRun.map((candidate) => [candidate.id, true]))
    };
    outputs = Object.fromEntries(cellsToRun.map((candidate) => [candidate.id, []]));
    testResults = {
      ...testResults,
      ...Object.fromEntries(cellsToRun.map((candidate) => [candidate.id, null]))
    };

    try {
      const response = await fetch(
        `${API_URL}/api/chapters/${chapterId}/cells/${cell.id}/run-through`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sources: Object.fromEntries(cellsToRun.map((candidate) => [candidate.id, sources[candidate.id]]))
          })
        }
      );
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? '批量运行失败');
      const nextOutputs = { ...outputs };
      for (const execution of result.executions ?? []) {
        nextOutputs[execution.cell_id] = execution.outputs ?? [];
      }
      outputs = nextOutputs;
      chapter.progress = result.progress;
      chapter = { ...chapter };
      if (result.stopped_at) {
        requestAnimationFrame(() => document.getElementById(result.stopped_at)?.scrollIntoView({ block: 'center' }));
      }
    } catch (error) {
      outputs = {
        ...outputs,
        [cell.id]: [{
          output_type: 'error',
          ename: 'RequestError',
          evalue: error instanceof Error ? error.message : String(error)
        }]
      };
    } finally {
      running = {
        ...running,
        ...Object.fromEntries(cellsToRun.map((candidate) => [candidate.id, false]))
      };
      runningThrough = null;
    }
  }

  function syncTestResultsFromProgress() {
    if (!chapter) return;
    testResults = Object.fromEntries(
      chapter.cells.map((candidate) => [candidate.id, chapter!.progress[candidate.id]?.test_result ?? null])
    );
  }

  async function restoreCell(cell: ChapterCell) {
    if (!chapter || resetting[cell.id]) return;
    if (!window.confirm(`还原“${cell.title ?? cell.id}”到课程初始代码？当前修改将被清除。`)) return;
    resetting = { ...resetting, [cell.id]: true };
    try {
      const response = await fetch(`${API_URL}/api/chapters/${chapterId}/cells/${cell.id}/reset`, {
        method: 'POST'
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? '还原失败');
      sources = { ...sources, [cell.id]: result.source };
      chapter.progress = result.progress;
      chapter = { ...chapter };
      outputs = {};
      syncTestResultsFromProgress();
      lspClient?.changeDocument(cell.id, result.source);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : String(error));
    } finally {
      resetting = { ...resetting, [cell.id]: false };
    }
  }

  async function restoreChapter() {
    if (!chapter || resettingChapter) return;
    if (!window.confirm('还原本章全部 Code Cell？所有代码修改和学习进度都会被清除。')) return;
    resettingChapter = true;
    try {
      const response = await fetch(`${API_URL}/api/chapters/${chapterId}/reset`, { method: 'POST' });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? '全部还原失败');
      sources = { ...sources, ...result.sources };
      chapter.progress = result.progress;
      chapter = { ...chapter };
      outputs = {};
      syncTestResultsFromProgress();
      for (const [cellId, source] of Object.entries(result.sources as Record<string, string>)) {
        lspClient?.changeDocument(cellId, source);
      }
    } catch (error) {
      window.alert(error instanceof Error ? error.message : String(error));
    } finally {
      resettingChapter = false;
    }
  }

  async function restartKernel() {
    await fetch(`${API_URL}/api/chapters/${chapterId}/kernel/restart`, { method: 'POST' });
    outputs = {};
    testResults = {};
  }

  function statusLabel(status: string): string {
    return { idle: '未开始', dirty: '需重检', failed: '未通过', passed: '已通过' }[status] ?? status;
  }

  function sectionTitle(cell: ChapterCell, index: number): string {
    if (index === 0) return '课程介绍';
    const heading = cell.source.match(/^#{1,6}\s+(.+)$/m)?.[1] ?? `知识点 ${index}`;
    return heading
      .replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1')
      .replace(/`/g, '')
      .replace(/^\d+\.\s*/, '');
  }

  function isTableOfContentsSection(cell: ChapterCell): boolean {
    if (cell.cell_type !== 'markdown' || cell.hidden) return false;
    const heading = cell.source.match(/^(#{1,6})\s+.+$/m);
    return heading !== null && heading[1].length <= 2;
  }

  $: exercises = chapter?.cells.filter((cell) => cell.exercise_id) ?? [];
  $: lessonSections = chapter?.cells.filter(isTableOfContentsSection) ?? [];
  $: passedCount = exercises.filter((cell) => chapter?.progress[cell.id]?.status === 'passed').length;
  $: progressPercent = exercises.length ? Math.round((passedCount / exercises.length) * 100) : 0;
</script>

<svelte:head>
  <title>Pushthrough · PyTorch Notebook Course</title>
  <meta name="description" content="一章一系统的交互式 PyTorch Notebook 课程" />
</svelte:head>

<div class="shell">
  <header class="topbar">
    {#if !navOpen}
      <button class="nav-toggle" aria-label="展开章节目录" aria-expanded="false" aria-controls="chapter-navigation" onclick={() => navOpen = true}>
        <svg aria-hidden="true" viewBox="0 0 20 20">
          <path d="M3 5h14M3 10h14M3 15h14" />
        </svg>
      </button>
    {/if}
    <a class="brand" href="/" aria-label="Pushthrough 首页">
      <span class="brand-mark">P</span>
      <span>Pushthrough</span>
    </a>
    <a class="course-list-link" href="/">所有课程</a>
    <div class={`lsp-state ${lspStatus}`} title={lspStatus === 'ready' ? 'Pyright 类型分析已连接' : lspStatus === 'error' ? 'Pyright 类型分析未连接' : '正在连接 Pyright'}>
      <span></span>{lspStatus === 'ready' ? '智能提示' : lspStatus === 'error' ? '提示离线' : '提示连接中'}
    </div>
    <div class="kernel-state"><span></span> 本地 Kernel</div>
    <button class="ghost-button" onclick={restartKernel}>↻ 重启 Kernel</button>
  </header>

  {#if loading}
    <main class="state-page">正在加载课程…</main>
  {:else if pageError}
    <main class="state-page error-page">
      <h1>课程服务尚未连接</h1>
      <p>{pageError}</p>
      <p>请先启动 FastAPI 服务，然后刷新页面。</p>
    </main>
  {:else if chapter}
    <div class:nav-open={navOpen} class="learning-layout">
      <aside class="rail" id="chapter-navigation">
        <button class="rail-collapse" aria-label="收起章节目录" title="收起目录" onclick={() => navOpen = false}>
          <svg aria-hidden="true" viewBox="0 0 20 20">
            <path d="m12 5-5 5 5 5" />
          </svg>
        </button>
        <div class="rail-progress">
          <div>
            <div class="rail-label">本章进度</div>
            <strong>{passedCount}/{exercises.length}</strong>
          </div>
          <span>{progressPercent}%</span>
        </div>
        <div class="progress-track"><span style={`width: ${progressPercent}%`}></span></div>
        <div class="toc-label">本章目录</div>
        <nav aria-label="Markdown 知识小节">
          {#each lessonSections as lesson, index}
            <a href={`#${lesson.id}`}>
              <span>{index === lessonSections.length - 1 ? '✓' : String(index).padStart(2, '0')}</span>
              {sectionTitle(lesson, index)}
            </a>
          {/each}
        </nav>
      </aside>

      <main class="course">
      <section class="hero">
        <div class="eyebrow">PYTORCH · CHAPTER {String(chapter.order ?? 1).padStart(2, '0')}</div>
        <h1>{chapter.title}</h1>
        <p>{chapter.description}</p>
        <div class="hero-meta">
          <span>{exercises.length} 个连续任务</span>
          <span>同一运行环境</span>
          <span>约 {chapter.duration_minutes ?? 60} 分钟</span>
        </div>
        <button class="restore-all-button" disabled={resettingChapter || Boolean(runningThrough)} onclick={restoreChapter}>
          {resettingChapter ? '正在还原…' : '↺ 全部还原 Code Cell'}
        </button>
      </section>

      {#each chapter.cells.filter((cell) => !cell.hidden) as cell}
        {#if cell.cell_type === 'markdown'}
          <section class="lesson prose" id={cell.id}>{@html markdown(cell.source)}</section>
        {:else}
          <section class="code-card" id={cell.id} class:finale={cell.type === 'finale'} class:demo={cell.type === 'example' && !cell.editable}>
            <div class="cell-header">
              <div>
                <div class="cell-kicker">{cell.type === 'finale' ? 'FINAL RUN' : cell.type === 'checkpoint' ? 'CHECKPOINT' : cell.type === 'setup' ? 'INITIALIZATION' : cell.type === 'example' && !cell.editable ? 'READ-ONLY EXAMPLE' : 'CODE CELL'}</div>
                <h3>{cell.title ?? '自由运行'}</h3>
              </div>
              {#if cell.exercise_id}
                <span class={`status ${chapter.progress[cell.id]?.status ?? 'idle'}`}>
                  {statusLabel(chapter.progress[cell.id]?.status ?? 'idle')}
                </span>
              {:else if cell.type === 'example' && !cell.editable}
                <span class="readonly-badge">只读 · 可运行</span>
              {:else if cell.type === 'setup'}
                <span class="readonly-badge">只读 · 自动执行</span>
              {/if}
            </div>

            {#if cell.depends_on.length}
              <div class="dependencies">依赖：{cell.depends_on.join(' · ')}</div>
            {/if}

            <CodeEditor
              value={sources[cell.id]}
              readonly={!cell.editable}
              {lspClient}
              lspCellId={lspClient?.hasCell(cell.id) ? cell.id : null}
              onchange={(source) => updateSource(cell.id, source)}
            />
            {#if cell.runnable}
              <CellOutput outputs={outputs[cell.id] ?? []} />
            {/if}
            {#if cell.editable}
              {#if testResults[cell.id]}
                <TestResult result={testResults[cell.id]!} />
              {/if}

              <div class="cell-actions">
              <button
                class="run-button reset"
                disabled={running[cell.id] || Boolean(runningThrough) || resetting[cell.id] || resettingChapter}
                onclick={() => restoreCell(cell)}
              >
                {resetting[cell.id] ? '还原中…' : '↺ 还原'}
              </button>
              <button class="run-button secondary" disabled={running[cell.id] || Boolean(runningThrough) || resetting[cell.id]} onclick={() => runCell(cell, false)}>
                {running[cell.id] ? '运行中…' : '▷ 运行'}
              </button>
              <button
                class="run-button secondary run-through"
                disabled={Boolean(runningThrough) || resetting[cell.id] || resettingChapter}
                title="从本章第一个 Code Cell 按顺序运行到这里"
                onclick={() => runThrough(cell)}
              >
                {runningThrough === cell.id ? '运行至此…' : '▶ 运行至此'}
              </button>
              {#if cell.test}
                <button
                  class="run-button primary"
                  disabled={running[cell.id] || Boolean(runningThrough) || resetting[cell.id] || prerequisiteIsMissing(cell)}
                  title={prerequisiteIsMissing(cell) ? '请先通过前置任务' : ''}
                  onclick={() => runCell(cell, true)}
                >
                  {prerequisiteIsMissing(cell) ? '先完成前置任务' : '运行并检查 →'}
                </button>
              {/if}
              </div>
            {:else if cell.runnable}
              <div class="cell-actions demo-actions">
                <button
                  class="run-button secondary demo-run"
                  disabled={running[cell.id] || Boolean(runningThrough) || resettingChapter}
                  onclick={() => runCell(cell, false)}
                >
                  {running[cell.id] ? '运行中…' : '▷ 运行示例'}
                </button>
              </div>
            {/if}
          </section>
        {/if}
      {/each}
      </main>
    </div>
  {/if}
</div>

<style>
  :global(*) { box-sizing: border-box; }
  :global(html) { scroll-behavior: smooth; }
  :global(body) {
    margin: 0;
    background: #f6f5f0;
    color: #242821;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  :global(button) { font: inherit; }

  .shell { min-height: 100vh; }
  .topbar {
    position: sticky;
    z-index: 20;
    top: 0;
    display: flex;
    align-items: center;
    height: 64px;
    padding: 0 28px;
    border-bottom: 1px solid #deddd6;
    background: rgba(246, 245, 240, 0.92);
    backdrop-filter: blur(12px);
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    color: #1f231d;
    text-decoration: none;
    font-weight: 800;
    letter-spacing: -0.02em;
  }
  .brand-mark {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border-radius: 9px;
    background: #20241e;
    color: #d9ff72;
  }
  .kernel-state {
    display: flex;
    align-items: center;
    gap: 7px;
    margin-left: 22px;
    color: #60665c;
    font-size: 13px;
  }
  .lsp-state { display: flex; align-items: center; gap: 7px; margin-left: auto; color: #7b8177; font-size: 12px; }
  .lsp-state span { width: 7px; height: 7px; border-radius: 50%; background: #c4c7bf; }
  .lsp-state.ready span { background: #75a83f; box-shadow: 0 0 0 3px #dceacb; }
  .lsp-state.error { color: #9a625c; }
  .lsp-state.error span { background: #c56a61; }
  .course-list-link {
    margin-left: 24px;
    color: #6a7066;
    text-decoration: none;
    font-size: 13px;
    font-weight: 650;
  }
  .course-list-link:hover { color: #252a22; }
  .nav-toggle {
    position: fixed;
    z-index: 19;
    top: 96px;
    left: 8px;
    display: grid;
    place-items: center;
    width: 22px;
    height: 46px;
    padding: 0;
    border: 1px solid #d6d5ce;
    border-radius: 7px;
    background: rgba(255, 255, 255, .9);
    color: #70766c;
    box-shadow: 0 3px 12px rgba(30, 34, 27, .08);
    cursor: pointer;
  }
  .nav-toggle:hover { background: #fff; color: #2c3229; }
  .nav-toggle svg { width: 13px; height: 13px; }
  .nav-toggle svg, .rail-collapse svg { fill: none; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 1.8; }
  .rail-collapse svg { width: 18px; height: 18px; }
  .kernel-state span {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #75a83f;
    box-shadow: 0 0 0 3px #dceacb;
  }
  .ghost-button {
    margin-left: 22px;
    padding: 8px 12px;
    border: 1px solid #d6d5ce;
    border-radius: 8px;
    background: transparent;
    color: #555b51;
    cursor: pointer;
  }
  .learning-layout { max-width: 820px; margin: 0 auto; }
  .learning-layout.nav-open { display: grid; grid-template-columns: 240px minmax(0, 820px); gap: 32px; max-width: 1140px; padding: 0 24px; }
  .rail { display: none; position: sticky; top: 88px; align-self: start; max-height: calc(100vh - 112px); margin-top: 32px; padding: 20px 16px; overflow: auto; border: 1px solid #dedfd8; border-radius: 14px; background: rgba(255, 255, 255, .72); }
  .nav-open .rail { display: block; }
  .rail-collapse { position: absolute; top: 12px; right: 12px; display: grid; place-items: center; width: 30px; height: 30px; padding: 0; border: 0; border-radius: 7px; background: transparent; color: #747b70; cursor: pointer; }
  .rail-collapse:hover { background: #eceee7; color: #282e25; }
  .rail-progress { display: flex; align-items: end; justify-content: space-between; }
  .rail-progress > div { padding-right: 34px; }
  .rail-progress > span { color: #7a8175; font-size: 11px; }
  .rail-label { color: #858b80; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
  .rail strong { display: block; margin-top: 5px; font-size: 22px; }
  .progress-track { height: 5px; overflow: hidden; border-radius: 9px; background: #dedfd8; }
  .progress-track span { display: block; height: 100%; border-radius: inherit; background: #769f3c; transition: width .3s ease; }
  .toc-label { margin-top: 26px; color: #858b80; font-size: 10px; font-weight: 800; letter-spacing: .12em; }
  nav { display: grid; gap: 3px; margin-top: 10px; }
  nav a { display: grid; grid-template-columns: 24px 1fr; align-items: start; gap: 8px; padding: 7px 6px; border-radius: 7px; color: #666d62; text-decoration: none; font-size: 12px; line-height: 1.4; }
  nav a:hover { background: #eef0e8; color: #2e342b; }
  nav a span { color: #8aa15c; font: 10px JetBrains Mono, monospace; }
  .course { width: 100%; min-width: 0; margin: 0 auto; padding: 78px 0 140px; }
  .hero { padding-bottom: 54px; border-bottom: 1px solid #dcdcd4; }
  .eyebrow, .cell-kicker { color: #779d43; font-size: 11px; font-weight: 850; letter-spacing: .13em; }
  .hero h1 { max-width: 680px; margin: 14px 0 18px; font-size: clamp(42px, 7vw, 66px); line-height: .98; letter-spacing: -.055em; }
  .hero > p { max-width: 650px; margin: 0; color: #686e64; font-size: 18px; line-height: 1.7; }
  .hero-meta { display: flex; gap: 10px; margin-top: 28px; flex-wrap: wrap; }
  .hero-meta span { padding: 7px 11px; border: 1px solid #d8d9d1; border-radius: 999px; color: #666c61; font-size: 12px; }
  .restore-all-button { margin-top: 18px; padding: 8px 11px; border: 1px solid #d4d6ce; border-radius: 8px; background: transparent; color: #666d62; cursor: pointer; font-size: 12px; font-weight: 700; }
  .restore-all-button:hover:not(:disabled) { border-color: #aeb2a7; background: #eeefe9; color: #30362d; }
  .restore-all-button:disabled { cursor: not-allowed; opacity: .48; }
  .lesson { padding: 50px 12px 20px; scroll-margin-top: 78px; }
  .prose :global(h1) { display: none; }
  .prose :global(h2) { margin: 0 0 14px; font-size: 27px; letter-spacing: -.035em; }
  .prose :global(p) { margin: 0; color: #62685e; font-size: 16px; line-height: 1.8; }
  .prose :global(p + p), .prose :global(p + ul), .prose :global(ul + p), .prose :global(pre) { margin-top: 14px; }
  .prose :global(h3) { margin: 24px 0 10px; font-size: 15px; }
  .prose :global(ul) { margin-bottom: 0; padding-left: 22px; color: #62685e; line-height: 1.8; }
  .prose :global(pre) { overflow-x: auto; padding: 14px 16px; border: 1px solid #dedfd8; border-radius: 10px; background: #eeeee8; }
  .prose :global(pre code) { padding: 0; background: transparent; }
  .prose :global(code) { padding: 2px 5px; border-radius: 5px; background: #e8e8e1; color: #343b30; font: 13px JetBrains Mono, monospace; }
  .code-card { overflow: hidden; margin: 24px 0 42px; border: 1px solid #d8d8d1; border-radius: 14px; background: #fff; box-shadow: 0 8px 30px rgba(32, 35, 28, .06); scroll-margin-top: 84px; }
  .code-card.demo { margin: 18px 0 30px; border-color: #d9dfcf; box-shadow: none; }
  .code-card.finale { border-color: #aec678; box-shadow: 0 10px 36px rgba(91, 123, 46, .12); }
  .cell-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 18px; }
  .cell-header h3 { margin: 4px 0 0; font-size: 16px; }
  .status { padding: 5px 9px; border-radius: 999px; background: #eeeee9; color: #73786f; font-size: 11px; font-weight: 750; }
  .status.passed { background: #e8f2d8; color: #456426; }
  .status.failed { background: #fee8e4; color: #a04035; }
  .status.dirty { background: #fff0c9; color: #86611a; }
  .readonly-badge { padding: 5px 9px; border-radius: 999px; background: #edf2e5; color: #62784a; font-size: 11px; font-weight: 750; }
  .dependencies { padding: 8px 18px; border-top: 1px solid #ecece6; background: #fafaf7; color: #858a81; font-size: 11px; }
  .cell-actions { display: flex; justify-content: flex-end; gap: 9px; padding: 12px 14px; border-top: 1px solid #ecece6; }
  .run-button { padding: 9px 14px; border-radius: 8px; cursor: pointer; font-weight: 700; font-size: 13px; }
  .run-button.reset { margin-right: auto; border: 0; background: transparent; color: #7b8177; }
  .run-button.reset:hover:not(:disabled) { background: #f0f1eb; color: #333a30; }
  .run-button.secondary { border: 1px solid #d8d9d2; background: white; color: #4f554b; }
  .run-button.run-through { color: #5f7e36; }
  .run-button.primary { min-width: 138px; border: 1px solid #20241e; background: #20241e; color: #e5ff9b; }
  .run-button:disabled { cursor: not-allowed; opacity: .48; }
  .state-page { display: grid; place-content: center; min-height: calc(100vh - 64px); color: #777d73; }
  .error-page { text-align: center; }
  .error-page h1 { color: #343830; }

  @media (max-width: 900px) {
    .learning-layout.nav-open { grid-template-columns: 210px minmax(0, 1fr); gap: 18px; padding: 0 16px; }
    .hero h1 { font-size: clamp(38px, 7vw, 54px); }
  }
  @media (max-width: 759px) {
    .topbar { padding: 0 16px; }
    .course-list-link { display: none; }
    .nav-toggle { top: 78px; left: 6px; }
    .kernel-state, .lsp-state { display: none; }
    .ghost-button { margin-left: auto; }
    .learning-layout, .learning-layout.nav-open { display: block; max-width: none; padding: 0; }
    .rail { position: fixed; z-index: 18; top: 64px; bottom: 0; left: 0; width: min(86vw, 300px); max-height: none; margin: 0; border-radius: 0 14px 14px 0; background: #fafaf6; box-shadow: 14px 0 40px rgba(30, 34, 27, .16); }
    .course { width: min(100% - 28px, 820px); padding-top: 50px; }
    .hero h1 { font-size: 44px; }
    .lesson { padding-left: 4px; padding-right: 4px; }
    .cell-header { align-items: flex-start; gap: 12px; }
    .cell-actions { flex-wrap: wrap; }
    .run-button { flex: 1; }
  }
</style>
