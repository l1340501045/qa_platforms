# 前端表单模式（React + Ant Design + Zustand）

> 本文件记录仓库**真实存在**的表单写法（增/改/删 + 校验 + 反馈 + 数据流）。
> 范例文件：`web/src/pages/Systems/index.tsx`、`web/src/services/systemApi.ts`、`web/src/services/api.ts`。
> 技术栈：React 18 + Ant Design 5 + Zustand + axios。

---

## 数据流（四层，固定方向）

```
页面组件 (pages/*/index.tsx)
   ↓ 调 store action
Zustand store (stores/*.ts)
   ↓ 调 service 函数
service (services/*Api.ts)  ──→  axios 实例 (services/api.ts)
   ↓ 拦截器解包信封 {code,message,data} → data
后端 /api/v1/*
```

页面**不直接调 axios**；通过 store action（范例用 `useKnowledgeStore`）→ service 函数。

---

## 表单：`Form.useForm` + `Modal`

新建/编辑共用一个受控 `Modal`，内嵌 `Form`，靠 `editingXxx` 区分模式：

```tsx
// web/src/pages/Systems/index.tsx:41
const [form] = Form.useForm();
const [editingSystem, setEditingSystem] = useState<System | null>(null);
const [submitting, setSubmitting] = useState(false);
```

```tsx
// web/src/pages/Systems/index.tsx:169
<Modal
  title={editingSystem ? '编辑系统' : '新建系统'}
  open={modalOpen}
  onCancel={() => setModalOpen(false)}
  onOk={handleSubmit}
  confirmLoading={submitting}
  okText={editingSystem ? '保存' : '创建'}
  cancelText="取消"
  destroyOnHidden
>
  <Form form={form} layout="vertical">
    <Form.Item name="name" label="系统名称"
      rules={[{ required: true, message: '请输入系统名称' }]}>
      <Input placeholder="请输入系统名称" />
    </Form.Item>
    <Form.Item name="description" label="描述">
      <Input.TextArea rows={4} placeholder="请输入系统描述（可选）" />
    </Form.Item>
  </Form>
</Modal>
```

- 打开"新建"：`form.resetFields()` 后置空（`index.tsx:53`）。
- 打开"编辑"：`form.setFieldsValue({...})` 回填（`index.tsx:60`）。
- 校验规则写在 `Form.Item` 的 `rules`，必填用 `{ required: true, message: '...' }`。

---

## 提交：`validateFields` + store action + `message`

固定套路：先 `validateFields()`，再按模式调创建/更新，成功 `message.success`，**校验错误要 return 掉**（不弹业务错误 toast）：

```tsx
// web/src/pages/Systems/index.tsx:64
const handleSubmit = async () => {
  try {
    const values = await form.validateFields();
    setSubmitting(true);
    if (editingSystem) {
      await updateSystem(editingSystem.id, values);
      message.success('系统更新成功');
    } else {
      await createSystem(values);
      message.success('系统创建成功');
    }
    setModalOpen(false);
    form.resetFields();
  } catch (err: any) {
    if (err?.errorFields) return; // 表单校验错误，AntD 已就地提示
    message.error(err?.message || '操作失败');
  } finally {
    setSubmitting(false);
  }
};
```

`createSystem/updateSystem/deleteSystem` 是 store action，从 `useKnowledgeStore()` 解构（`index.tsx:26`）。

---

## 删除：`Modal.confirm`

破坏性操作用 `Modal.confirm` 二次确认，`onOk` 内 try/catch + `message`：

```tsx
// web/src/pages/Systems/index.tsx:87
Modal.confirm({
  title: '确认删除',
  content: `确定删除系统「${system.name}」？此操作不可撤销。`,
  okText: '删除', okType: 'danger', cancelText: '取消',
  onOk: async () => {
    try {
      await deleteSystem(system.id);
      message.success('删除成功');
    } catch (err: any) {
      message.error(err?.message || '删除失败');
    }
  },
});
```

---

## service 层：薄封装，返回解包后的 `data`

每个接口一个导出函数，调 `api`，`return res.data`（已被拦截器解过信封）：

```ts
// web/src/services/systemApi.ts:20
export async function createSystem(params: CreateSystemRequest): Promise<System> {
  const res = await api.post('/systems', params);
  return res.data;
}
```

---

## axios 实例与拦截器（已统一，勿在页面重复处理）

`web/src/services/api.ts` 已集中处理信封解包与错误：

- 请求拦截器注入 `X-Request-ID`（`api.ts:23`）。
- 响应拦截器：`{code:0,...,data}` → 把 `response.data` 替换成 `data`（`api.ts:38`）；`204` 直接透传（`api.ts:31`）。
- 错误拦截器：按 HTTP 状态弹对应 `message`，**404 不弹 toast**（留给页面级处理），最终 `reject(errorData)`（`api.ts:47`）。

→ 页面/ service 层因此**不用再解 `{code,data}` 信封**，直接拿 `res.data`；业务错误对象形如 `{error_code, message, request_id}`，用 `err?.message` 取文案即可。

---

## 速查清单（写新表单照此核对）

- [ ] 页面经 store action 调 service，不直接 `import api`
- [ ] `Form.useForm()` + `Modal`，`onOk=handleSubmit`、`confirmLoading={submitting}`
- [ ] 编辑用 `setFieldsValue` 回填，新建用 `resetFields`
- [ ] `handleSubmit` 内 `validateFields()`，`catch` 里 `if (err?.errorFields) return`
- [ ] 成功 `message.success`，失败 `message.error(err?.message || '...')`
- [ ] 删除等破坏性操作用 `Modal.confirm`
- [ ] service 函数 `return res.data`（不要再解信封）
