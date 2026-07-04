import test from 'node:test';
import assert from 'node:assert/strict';

import {
  filterCaseAssetTree,
  findCaseAssetNodeKeyForCase,
  getCasesForNode,
  getDefaultExpandedKeys,
  normalizeCaseTreeDocuments,
} from './caseAssetModel.ts';
import type { CaseTreeCase, CaseTreeDocument, Priority, ReviewStatus } from '../../types';

function makeCase(id: string, title: string, branchPath: string[]): CaseTreeCase {
  return {
    id,
    title,
    priority: 'P1' as Priority,
    trust_level: 1,
    review_status: 'pending' as ReviewStatus,
    iteration: 1,
    verdict: 'grounded',
    bucket: 'main',
    branch_path: branchPath,
  };
}

const caseA = makeCase('case-a', '账户选择弹窗第一页展示', ['账户选择弹窗（批创页）', '分页规则']);
const caseB = makeCase('case-b', '账户选择弹窗第二页展示', ['账户选择弹窗（批创页）', '分页规则']);
const caseC = makeCase('case-c', '账户选择弹窗权限不足提示', ['账户选择弹窗（批创页）', '异常场景']);
const caseD = makeCase('case-d', '头条账户授权入口展示', ['入口与页面预览']);

function makeTree(): CaseTreeDocument[] {
  return [
    {
      document_id: 'doc-1',
      document_title: '漫剧批创 PRD',
      modules: [
        {
          module_name: '账户授权',
          case_count: 4,
          cases: [caseA, caseB, caseC, caseD],
          branches: [
            {
              branch_name: '账户选择弹窗（批创页） / 分页规则',
              branch_path: ['账户选择弹窗（批创页）', '分页规则'],
              case_count: 2,
              cases: [caseA, caseB],
            },
            {
              branch_name: '账户选择弹窗（批创页） / 异常场景',
              branch_path: ['账户选择弹窗（批创页）', '异常场景'],
              case_count: 1,
              cases: [caseC],
            },
            {
              branch_name: '入口与页面预览',
              branch_path: ['入口与页面预览'],
              case_count: 1,
              cases: [caseD],
            },
          ],
        },
      ],
    },
  ];
}

test('normalizeCaseTreeDocuments builds recursive branch nodes from branch_path', () => {
  const tree = normalizeCaseTreeDocuments(makeTree(), { rootTitle: '漫剧批创系统' });

  assert.equal(tree.root.title, '漫剧批创系统');
  assert.equal(tree.root.count, 4);
  assert.deepEqual(tree.root.caseIds, ['case-a', 'case-b', 'case-c', 'case-d']);

  const doc = tree.root.children[0];
  const module = doc.children[0];
  assert.equal(module.title, '账户授权');
  assert.equal(module.count, 4);

  const accountDialog = module.children.find((node) => node.title === '账户选择弹窗（批创页）');
  assert.ok(accountDialog);
  assert.equal(accountDialog.count, 3);
  assert.deepEqual(
    accountDialog.children.map((node) => node.title),
    ['分页规则', '异常场景'],
  );

  const pagination = accountDialog.children.find((node) => node.title === '分页规则');
  assert.ok(pagination);
  assert.equal(pagination.count, 2);
  assert.deepEqual(pagination.caseIds, ['case-a', 'case-b']);
});

test('getCasesForNode returns all cases under a module or intermediate branch', () => {
  const tree = normalizeCaseTreeDocuments(makeTree());
  const module = tree.root.children[0].children[0];
  const accountDialog = module.children.find((node) => node.title === '账户选择弹窗（批创页）');

  assert.ok(accountDialog);
  assert.deepEqual(
    getCasesForNode(module.key, tree).map((item) => item.id),
    ['case-a', 'case-b', 'case-c', 'case-d'],
  );
  assert.deepEqual(
    getCasesForNode(accountDialog.key, tree).map((item) => item.id),
    ['case-a', 'case-b', 'case-c'],
  );
});

test('findCaseAssetNodeKeyForCase returns the deepest node that contains the case', () => {
  const tree = normalizeCaseTreeDocuments(makeTree());
  const nodeKey = findCaseAssetNodeKeyForCase(tree.root, 'case-c');

  assert.ok(nodeKey);
  assert.deepEqual(
    getCasesForNode(nodeKey, tree).map((item) => item.id),
    ['case-c'],
  );
});

test('filterCaseAssetTree keeps ancestors when keyword matches a nested case title', () => {
  const tree = normalizeCaseTreeDocuments(makeTree());
  const filtered = filterCaseAssetTree(tree.root, '权限不足', tree.caseMap);

  assert.ok(filtered);
  assert.equal(filtered.children.length, 1);
  const module = filtered.children[0].children[0];
  assert.equal(module.title, '账户授权');
  assert.deepEqual(
    module.children.map((node) => node.title),
    ['账户选择弹窗（批创页）'],
  );
  assert.deepEqual(
    module.children[0].children.map((node) => node.title),
    ['异常场景'],
  );
});

test('getDefaultExpandedKeys expands root and document levels without opening branch subtrees', () => {
  const tree = normalizeCaseTreeDocuments(makeTree());

  assert.deepEqual(getDefaultExpandedKeys(tree.root), ['root', 'doc::doc-1']);
});
