import test from 'node:test';
import assert from 'node:assert/strict';

import { getFailedStageDetail } from './stageFailure.ts';
import type { StageInfo } from '../types';

const completedStage: StageInfo = { name: 'parse', status: 'completed' };

test('getFailedStageDetail prefers failed stage with error message', () => {
  const detail = getFailedStageDetail([
    completedStage,
    { name: 'comprehend', status: 'failed', error_message: 'Gateway timeout' },
    { name: 'write-cases', status: 'failed', error_message: null },
  ]);

  assert.deepEqual(detail, {
    stageName: 'comprehend',
    errorMessage: 'Gateway timeout',
  });
});

test('getFailedStageDetail falls back to failed stage without message', () => {
  const detail = getFailedStageDetail([
    completedStage,
    { name: 'write-cases', status: 'failed', error_message: '   ' },
  ]);

  assert.deepEqual(detail, {
    stageName: 'write-cases',
    errorMessage: null,
  });
});

test('getFailedStageDetail can use current stage when backend cannot mark a failed stage', () => {
  const detail = getFailedStageDetail([completedStage], 'gate');

  assert.deepEqual(detail, {
    stageName: 'gate',
    errorMessage: null,
  });
});

test('getFailedStageDetail returns null when there is no failure signal', () => {
  assert.equal(getFailedStageDetail([completedStage]), null);
});
