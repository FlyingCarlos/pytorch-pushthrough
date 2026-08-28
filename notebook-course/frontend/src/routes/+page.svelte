<script lang="ts">
  import { onMount } from 'svelte';
  import type { ChapterSummary } from '$lib/types';

  const API_URL = import.meta.env.VITE_API_URL ?? '';

  let chapters: ChapterSummary[] = [];
  let loading = true;
  let pageError = '';

  onMount(loadChapters);

  async function loadChapters() {
    try {
      const response = await fetch(`${API_URL}/api/chapters`);
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      chapters = data.chapters;
    } catch (error) {
      pageError = error instanceof Error ? error.message : String(error);
    } finally {
      loading = false;
    }
  }

  function actionLabel(chapter: ChapterSummary): string {
    if (chapter.progress_percent === 100) return '重新学习';
    if (chapter.passed_count > 0) return '继续学习';
    return '开始课程';
  }

  $: totalExercises = chapters.reduce((sum, chapter) => sum + chapter.exercise_count, 0);
  $: completedExercises = chapters.reduce((sum, chapter) => sum + chapter.passed_count, 0);
</script>

<svelte:head>
  <title>课程列表 · Pushthrough</title>
  <meta name="description" content="连续构建真实系统的交互式 PyTorch Notebook 课程" />
</svelte:head>

<div class="page">
  <header class="topbar">
    <a class="brand" href="/" aria-label="Pushthrough 首页">
      <span class="brand-mark">P</span>
      <span>Pushthrough</span>
    </a>
    <span class="tagline">PyTorch Notebook Courses</span>
  </header>

  <main>
    <section class="hero">
      <div class="eyebrow">LEARN BY BUILDING</div>
      <h1>从 Tensor 开始，<br />真正写会 PyTorch。</h1>
      <p>每章都是一个可运行的 Notebook 项目。学到的每个概念，都会在后面的代码里继续工作。</p>
      <div class="stats">
        <div><strong>{chapters.length}</strong><span>课程</span></div>
        <div><strong>{totalExercises}</strong><span>连续任务</span></div>
        <div><strong>{completedExercises}</strong><span>已经通过</span></div>
      </div>
    </section>

    <section class="catalog">
      <div class="section-heading">
        <div>
          <div class="eyebrow">COURSE CATALOG</div>
          <h2>课程列表</h2>
        </div>
        <p>按顺序学习，每章都以前一章建立的直觉为基础。</p>
      </div>

      {#if loading}
        <div class="state">正在读取本地课程…</div>
      {:else if pageError}
        <div class="state error">
          <strong>课程服务尚未连接</strong>
          <span>{pageError}</span>
        </div>
      {:else if chapters.length === 0}
        <div class="state">还没有课程。在 courses 目录添加一个 chapter.ipynb 即可。</div>
      {:else}
        <div class="course-grid">
          {#each chapters as chapter}
            <a class="course-card" href={`/chapters/${chapter.id}`}>
              <div class="card-topline">
                <span class="chapter-number">{String(chapter.order).padStart(2, '0')}</span>
                <div class="badges">
                  <span>{chapter.level}</span>
                  <span>{chapter.duration_minutes ?? 60} 分钟</span>
                </div>
              </div>
              <h3>{chapter.title}</h3>
              <p>{chapter.description}</p>
              <div class="progress-copy">
                <span>{chapter.passed_count}/{chapter.exercise_count} 个任务</span>
                <span>{chapter.progress_percent}%</span>
              </div>
              <div class="progress-track"><span style={`width: ${chapter.progress_percent}%`}></span></div>
              <div class="card-action">
                <span>{actionLabel(chapter)}</span>
                <strong>→</strong>
              </div>
            </a>
          {/each}
        </div>
      {/if}
    </section>

    <section class="authoring-note">
      <div class="note-icon">+</div>
      <div>
        <strong>新增课程无需修改列表页面</strong>
        <p>在 <code>courses/&lt;chapter-id&gt;/</code> 添加标准 Notebook 和测试文件，课程会自动出现在这里。</p>
      </div>
    </section>
  </main>
</div>

<style>
  :global(*) { box-sizing: border-box; }
  :global(body) {
    margin: 0;
    background: #f6f5f0;
    color: #242821;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .page { min-height: 100vh; }
  .topbar {
    display: flex;
    align-items: center;
    height: 64px;
    padding: 0 28px;
    border-bottom: 1px solid #deddd6;
  }
  .brand { display: flex; align-items: center; gap: 10px; color: #1f231d; text-decoration: none; font-weight: 800; letter-spacing: -.02em; }
  .brand-mark { display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px; background: #20241e; color: #d9ff72; }
  .tagline { margin-left: auto; color: #858a80; font-size: 12px; letter-spacing: .04em; }
  main { width: min(1120px, calc(100% - 48px)); margin: 0 auto; padding: 88px 0 120px; }
  .hero { display: grid; grid-template-columns: 1fr 340px; column-gap: 80px; align-items: end; padding-bottom: 76px; border-bottom: 1px solid #dcdcd4; }
  .eyebrow { color: #779d43; font-size: 11px; font-weight: 850; letter-spacing: .13em; }
  .hero .eyebrow { grid-column: 1 / -1; }
  h1 { margin: 16px 0 0; font-size: clamp(48px, 7vw, 76px); line-height: .98; letter-spacing: -.06em; }
  .hero > p { margin: 0 0 6px; color: #646a60; font-size: 17px; line-height: 1.8; }
  .stats { grid-column: 1 / -1; display: flex; gap: 48px; margin-top: 48px; }
  .stats div { display: flex; align-items: baseline; gap: 9px; }
  .stats strong { font-size: 26px; letter-spacing: -.04em; }
  .stats span { color: #7c8277; font-size: 12px; }
  .catalog { padding-top: 72px; }
  .section-heading { display: flex; align-items: end; justify-content: space-between; gap: 32px; margin-bottom: 28px; }
  .section-heading h2 { margin: 8px 0 0; font-size: 34px; letter-spacing: -.04em; }
  .section-heading p { max-width: 390px; margin: 0; color: #73796f; font-size: 14px; line-height: 1.6; }
  .course-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
  .course-card { display: flex; flex-direction: column; min-height: 430px; padding: 24px; overflow: hidden; border: 1px solid #d8d9d1; border-radius: 18px; background: #fff; color: inherit; text-decoration: none; box-shadow: 0 8px 30px rgba(32, 35, 28, .05); transition: transform .2s ease, box-shadow .2s ease; }
  .course-card:hover { transform: translateY(-3px); box-shadow: 0 16px 38px rgba(32, 35, 28, .1); }
  .card-topline { display: flex; align-items: center; justify-content: space-between; }
  .chapter-number { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 50%; background: #20241e; color: #dfff83; font-size: 13px; font-weight: 800; }
  .badges { display: flex; gap: 6px; }
  .badges span { padding: 6px 9px; border-radius: 999px; background: #f0f1eb; color: #6f756a; font-size: 11px; }
  .course-card h3 { margin: 34px 0 0; font-size: 25px; letter-spacing: -.035em; }
  .course-card > p { margin: 12px 0 28px; color: #697065; line-height: 1.7; font-size: 14px; }
  .progress-copy { display: flex; justify-content: space-between; margin-top: auto; color: #858a80; font-size: 11px; }
  .progress-track { height: 5px; margin-top: 8px; overflow: hidden; border-radius: 8px; background: #e8e9e3; }
  .progress-track span { display: block; height: 100%; border-radius: inherit; background: #7ba641; }
  .card-action { display: flex; justify-content: space-between; align-items: center; margin-top: 22px; padding-top: 16px; border-top: 1px solid #ebebe6; font-size: 13px; font-weight: 750; }
  .card-action strong { color: #6f9837; font-size: 20px; transition: transform .2s ease; }
  .course-card:hover .card-action strong { transform: translateX(4px); }
  .state { display: grid; gap: 8px; place-items: center; min-height: 240px; border: 1px dashed #d4d5cd; border-radius: 16px; color: #7c8278; }
  .state.error { color: #954239; }
  .state.error span { max-width: 600px; font-size: 12px; }
  .authoring-note { display: flex; align-items: center; gap: 16px; margin-top: 28px; padding: 22px; border: 1px dashed #cfd5c5; border-radius: 14px; color: #596151; }
  .note-icon { display: grid; flex: 0 0 auto; place-items: center; width: 38px; height: 38px; border-radius: 10px; background: #e9f1dc; color: #638c2c; font-size: 22px; }
  .authoring-note p { margin: 4px 0 0; color: #7a8075; font-size: 13px; }
  code { padding: 2px 5px; border-radius: 4px; background: #e8e9e2; font-family: JetBrains Mono, monospace; }
  @media (max-width: 820px) {
    main { width: min(100% - 28px, 1120px); padding-top: 54px; }
    .hero { display: block; }
    .hero > p { margin-top: 28px; }
    .stats { gap: 24px; }
    .section-heading { align-items: flex-start; flex-direction: column; }
    .course-grid { grid-template-columns: 1fr; }
  }
  @media (max-width: 520px) {
    .topbar { padding: 0 16px; }
    .tagline { display: none; }
    h1 { font-size: 47px; }
    .stats { flex-wrap: wrap; }
    .course-card { min-height: 400px; }
  }
</style>
