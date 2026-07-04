import test from 'node:test';
import assert from 'node:assert/strict';

import {
  formatViewableBatchStatus,
  isViewableBatchStatus,
} from './batchVisibility.ts';

test('viewable batch status matches backend asset/export scope', () => {
  assert.equal(isViewableBatchStatus('pending_review'), true);
  assert.equal(isViewableBatchStatus('completed'), true);
  assert.equal(isViewableBatchStatus('archived'), true);
  assert.equal(isViewableBatchStatus('running'), false);
  assert.equal(isViewableBatchStatus('failed'), false);
  assert.equal(isViewableBatchStatus('suspended'), false);
});

test('formatViewableBatchStatus preserves unknown backend status', () => {
  assert.equal(formatViewableBatchStatus('pending_review'), '待审阅');
  assert.equal(formatViewableBatchStatus('custom'), 'custom');
});
