<script lang="ts">
  import type { TestResult } from '$lib/types';
  export let result: TestResult;
</script>

<div class:passed={result.passed} class="test-result">
  <div class="summary">
    <span class="summary-icon">{result.passed ? '✓' : '!'}</span>
    <strong>{result.message}</strong>
  </div>
  <ul>
    {#each result.checks as check}
      <li class:passed={check.passed}>
        <span>{check.passed ? '✓' : '×'}</span>
        <div>
          <strong>{check.label}</strong>
          {#if check.hint}<p>{check.hint}</p>{/if}
        </div>
      </li>
    {/each}
  </ul>
</div>

<style>
  .test-result {
    padding: 16px 18px;
    border-top: 1px solid #f0cbc5;
    background: #fff2ef;
    color: #8e3228;
  }

  .test-result.passed {
    border-color: #cddfb0;
    background: #f2f8e8;
    color: #355a22;
  }

  .summary,
  li {
    display: flex;
    align-items: flex-start;
    gap: 10px;
  }

  .summary-icon {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: currentColor;
    color: white;
  }

  ul {
    display: grid;
    gap: 8px;
    margin: 14px 0 0 32px;
    padding: 0;
    list-style: none;
  }

  li > span {
    font-weight: 800;
  }

  li.passed {
    color: #466737;
  }

  li strong {
    font-size: 13px;
  }

  p {
    margin: 2px 0 0;
    color: #72534f;
    font-size: 12px;
  }
</style>
