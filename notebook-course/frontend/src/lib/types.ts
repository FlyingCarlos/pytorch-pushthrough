export type CellStatus = 'idle' | 'dirty' | 'failed' | 'passed';

export type TestCheck = {
  label: string;
  passed: boolean;
  hint?: string | null;
};

export type TestResult = {
  passed: boolean;
  checks: TestCheck[];
  message: string;
};

export type CellProgress = {
  status: CellStatus;
  test_result?: TestResult | null;
};

export type ChapterCell = {
  id: string;
  cell_type: 'markdown' | 'code';
  type: 'lesson' | 'setup' | 'example' | 'exercise' | 'checkpoint' | 'finale';
  title?: string | null;
  source: string;
  exercise_id?: string | null;
  depends_on: string[];
  test?: string | null;
  editable: boolean;
  runnable: boolean;
  hidden: boolean;
};

export type Chapter = {
  id: string;
  title: string;
  description: string;
  duration_minutes?: number | null;
  order?: number;
  level?: string;
  cells: ChapterCell[];
  progress: Record<string, CellProgress>;
};

export type ChapterSummary = {
  id: string;
  title: string;
  description: string;
  duration_minutes?: number | null;
  order: number;
  level: string;
  exercise_count: number;
  passed_count: number;
  progress_percent: number;
};

export type NotebookOutput = {
  output_type: 'stream' | 'display_data' | 'execute_result' | 'error';
  name?: string;
  text?: string;
  data?: Record<string, unknown>;
  ename?: string;
  evalue?: string;
  traceback?: string[];
};
