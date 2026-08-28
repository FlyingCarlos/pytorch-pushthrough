<script lang="ts">
  import type { NotebookOutput } from '$lib/types';

  export let outputs: NotebookOutput[] = [];

  function text(value: unknown): string {
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  }
</script>

{#if outputs.length}
  <div class="outputs" aria-live="polite">
    {#each outputs as output}
      {#if output.output_type === 'stream'}
        <pre class:error={output.name === 'stderr'}>{output.text}</pre>
      {:else if output.output_type === 'error'}
        <div class="exception">
          <strong>{output.ename}: {output.evalue}</strong>
          {#if output.traceback?.length}<pre>{output.traceback.join('\n')}</pre>{/if}
        </div>
      {:else if output.data?.['image/png']}
        <img src={`data:image/png;base64,${output.data['image/png']}`} alt="Cell 运行结果" />
      {:else if output.data?.['text/html']}
        <div class="html-output">{@html text(output.data['text/html'])}</div>
      {:else if output.data?.['text/plain']}
        <pre>{text(output.data['text/plain'])}</pre>
      {/if}
    {/each}
  </div>
{/if}

<style>
  .outputs {
    border-top: 1px solid #2c3138;
    background: #101216;
    color: #d8ddd2;
    padding: 14px 18px;
  }

  pre {
    margin: 0;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    font: 13px/1.65 JetBrains Mono, SFMono-Regular, Consolas, monospace;
  }

  pre.error,
  .exception {
    color: #ff9c91;
  }

  .exception pre {
    margin-top: 8px;
    opacity: 0.86;
  }

  img {
    display: block;
    max-width: 100%;
    background: white;
    border-radius: 8px;
  }

  .html-output :global(table) {
    border-collapse: collapse;
  }
</style>
