import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildCaseAssetBatchScopeHelp,
  buildCaseAssetBatchScopeLabel,
  formatCaseAssetBatchStatus,
  isCaseAssetVisibleBatch,
} from './caseAssetBatchScope.ts';

test('case asset visible batch status matches backend default case-tree scope', () => {
  assert.equal(isCaseAssetVisibleBatch('pending_review'), true);
  assert.equal(isCaseAssetVisibleBatch('completed'), true);
  assert.equal(isCaseAssetVisibleBatch('archived'), true);
  assert.equal(isCaseAssetVisibleBatch('running'), false);
  assert.equal(isCaseAssetVisibleBatch('failed'), false);
});

test('default case asset batch scope copy explains per-document latest visible batches', () => {
  assert.equal(
    buildCaseAssetBatchScopeLabel({ visibleBatchCount: 3 }),
    '默认：各文档最新可见批次',
  );
  assert.match(
    buildCaseAssetBatchScopeHelp({ visibleBatchCount: 3 }),
    /每份文档最新的待审阅\/已完成\/已落库批次/,
  );
  assert.match(buildCaseAssetBatchScopeHelp({ visibleBatchCount: 3 }), /3 个可见批次/);
});

test('explicit case asset batch scope names the selected batch', () => {
  const selectedBatch = {
    document_title: '漫剧批创 PRD',
    status: 'pending_review',
    total_cases: 128,
    created_at: '2026-07-04T08:00:00Z',
  };

  assert.equal(
    buildCaseAssetBatchScopeLabel({ selectedBatch, visibleBatchCount: 1 }),
    '漫剧批创 PRD · 待审阅',
  );
  assert.match(
    buildCaseAssetBatchScopeHelp({ selectedBatch, visibleBatchCount: 1 }),
    /128 例 · 待审阅/,
  );
});

test('batch scope copy does not hide batch list loading failure', () => {
  assert.equal(
    buildCaseAssetBatchScopeLabel({ batchError: 'network', visibleBatchCount: 0 }),
    '默认：各文档最新可见批次（批次列表未加载）',
  );
  assert.match(
    buildCaseAssetBatchScopeHelp({ batchError: 'network', visibleBatchCount: 0 }),
    /不能据此判断没有历史批次/,
  );
});

test('formatCaseAssetBatchStatus preserves unknown backend status', () => {
  assert.equal(formatCaseAssetBatchStatus('custom'), 'custom');
});
