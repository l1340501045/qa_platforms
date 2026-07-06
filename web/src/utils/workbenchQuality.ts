import type { CaseBucket, CaseTreeCase, CaseVerdict } from '../types';

export interface WorkbenchQualityStats {
  main: number;
  needs_spec: number;
  to_fix: number;
  grounded: number;
  ungrounded: number;
  undefined: number;
  conflict: number;
}

export const EMPTY_WORKBENCH_QUALITY_STATS: WorkbenchQualityStats = {
  main: 0,
  needs_spec: 0,
  to_fix: 0,
  grounded: 0,
  ungrounded: 0,
  undefined: 0,
  conflict: 0,
};

type QualityCase = Pick<CaseTreeCase, 'bucket' | 'verdict'>;

function addBucket(stats: WorkbenchQualityStats, bucket: CaseBucket | null | undefined) {
  if (!bucket) return;
  stats[bucket] += 1;
}

function addVerdict(stats: WorkbenchQualityStats, verdict: CaseVerdict | null | undefined) {
  if (!verdict) return;
  stats[verdict] += 1;
}

export function buildWorkbenchQualityStats(cases: ReadonlyArray<QualityCase>): WorkbenchQualityStats {
  const stats: WorkbenchQualityStats = { ...EMPTY_WORKBENCH_QUALITY_STATS };

  for (const item of cases) {
    addBucket(stats, item.bucket);
    addVerdict(stats, item.verdict);
  }

  return stats;
}

export function getHumanReviewCount(stats: WorkbenchQualityStats): number {
  return stats.ungrounded + stats.undefined;
}
