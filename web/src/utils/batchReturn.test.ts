import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildNotificationBatchUrl,
  getNotificationReviewStatus,
} from './batchReturn.ts';

test('notification batch url returns to the matching workbench lane', () => {
  assert.equal(
    buildNotificationBatchUrl('batch-1', 'batch_completed'),
    '/batches/batch-1?from=review&status=pending_review',
  );
  assert.equal(
    buildNotificationBatchUrl('batch-2', 'batch_failed'),
    '/batches/batch-2?from=review&status=failed',
  );
  assert.equal(
    buildNotificationBatchUrl('batch-3', 'batch_suspended'),
    '/batches/batch-3?from=review&status=suspended',
  );
});

test('batch completed notification means pending review, not archived completion', () => {
  assert.equal(getNotificationReviewStatus('batch_completed'), 'pending_review');
});
