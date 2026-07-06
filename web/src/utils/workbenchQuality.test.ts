import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildWorkbenchQualityStats,
  getHumanReviewCount,
} from './workbenchQuality.ts';

test('buildWorkbenchQualityStats counts bucket and verdict independently', () => {
  const stats = buildWorkbenchQualityStats([
    { bucket: 'main', verdict: 'grounded' },
    { bucket: 'main', verdict: 'ungrounded' },
    { bucket: 'needs_spec', verdict: 'undefined' },
    { bucket: 'to_fix', verdict: 'conflict' },
    { bucket: null, verdict: null },
  ]);

  assert.deepEqual(stats, {
    main: 2,
    needs_spec: 1,
    to_fix: 1,
    grounded: 1,
    ungrounded: 1,
    undefined: 1,
    conflict: 1,
  });
});

test('getHumanReviewCount combines ungrounded and undefined cases', () => {
  const stats = buildWorkbenchQualityStats([
    { bucket: 'main', verdict: 'ungrounded' },
    { bucket: 'needs_spec', verdict: 'undefined' },
    { bucket: 'to_fix', verdict: 'conflict' },
  ]);

  assert.equal(getHumanReviewCount(stats), 2);
});
