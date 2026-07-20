import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
  message,
} from 'antd';
import {
  ApiOutlined,
  DatabaseOutlined,
  EyeOutlined,
  PictureOutlined,
  ReloadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';

import PageHeader from '../../components/layout/PageHeader';
import PageShell from '../../components/layout/PageShell';
import { layoutTokens } from '../../components/layout/tokens';
import {
  buildConnectionRequest,
  clearSensitiveModelFields,
  finalizeConnectionTestFields,
  getApiKeyValidationError,
  getBaseUrlValidationError,
  isModelSettingsConflict,
  shouldSyncModelForm,
  type ModelFormValues,
} from '../../services/modelSettingsModel';
import { useModelSettingsStore } from '../../stores/modelSettingsStore';
import type {
  AIModelRole,
  AIModelSetting,
  ModelConnectionRequest,
  ModelConnectionTestResult,
  SaveModelSettingRequest,
} from '../../types';
import { getErrorMessage } from '../../utils/errorMessage';

const { Paragraph, Text } = Typography;

const ROLE_ICON: Record<AIModelRole, ReactNode> = {
  primary: <RobotOutlined />,
  vision: <PictureOutlined />,
  verify: <SafetyCertificateOutlined />,
  embedding: <DatabaseOutlined />,
};

const KEY_STATUS = {
  configured: { color: 'success', text: 'Key 已配置' },
  missing: { color: 'default', text: 'Key 未配置' },
  unreadable: { color: 'error', text: 'Key 需重新填写' },
} as const;

function formatTestedAt(value: string | null): string {
  if (!value) return '尚未通过页面测试';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '测试时间未知' : date.toLocaleString('zh-CN', { hour12: false });
}

interface ModelSettingCardProps {
  setting: AIModelSetting;
  revision: number;
  persistenceReady: boolean;
  operation: {
    testing: boolean;
    saving: boolean;
    lastTest: ModelConnectionTestResult | null;
  };
  testModel: (role: AIModelRole, request: ModelConnectionRequest) => Promise<ModelConnectionTestResult | undefined>;
  saveModel: (role: AIModelRole, request: SaveModelSettingRequest) => Promise<unknown>;
  clearLastTest: (role: AIModelRole) => void;
  refreshSettings: () => Promise<void>;
}

function ModelSettingCard({
  setting,
  revision,
  persistenceReady,
  operation,
  testModel,
  saveModel,
  clearLastTest,
  refreshSettings,
}: ModelSettingCardProps) {
  const [form] = Form.useForm<ModelFormValues>();
  const [actionError, setActionError] = useState<string | null>(null);
  const [retainingTestedKey, setRetainingTestedKey] = useState(false);
  const lastSyncedSetting = useRef<AIModelSetting | null>(null);
  const [modal, modalContext] = Modal.useModal();
  const keyStatus = KEY_STATUS[setting.api_key_status];
  const busy = operation.testing || operation.saving;

  useEffect(() => {
    if (!shouldSyncModelForm(lastSyncedSetting.current, setting)) {
      lastSyncedSetting.current = setting;
      return;
    }
    form.setFieldsValue({
      base_url: setting.base_url,
      model_name: setting.model_name,
      api_key: '',
    });
    lastSyncedSetting.current = setting;
    setRetainingTestedKey(false);
    setActionError(null);
  }, [form, setting]);

  const clearApiKey = () => {
    const current = form.getFieldsValue();
    form.setFieldsValue(clearSensitiveModelFields(current));
    setRetainingTestedKey(false);
  };

  const handleValuesChange = (changedValues: Partial<ModelFormValues>) => {
    clearLastTest(setting.role);
    setActionError(null);

    const endpointChanged = 'base_url' in changedValues || 'model_name' in changedValues;
    const apiKeyChanged = 'api_key' in changedValues;
    if (retainingTestedKey && endpointChanged && !apiKeyChanged) {
      clearApiKey();
    } else if (apiKeyChanged) {
      setRetainingTestedKey(false);
    }
  };

  const validateRequest = async (): Promise<ModelConnectionRequest | null> => {
    try {
      return buildConnectionRequest(await form.validateFields());
    } catch {
      return null;
    }
  };

  const handleTest = async () => {
    const request = await validateRequest();
    if (!request) return;

    setActionError(null);
    let succeeded = false;
    try {
      const result = await testModel(setting.role, request);
      succeeded = Boolean(result?.ok);
      setRetainingTestedKey(succeeded && Boolean(request.api_key));
      if (result?.ok) {
        message.success(`${setting.display_name}连接成功`);
      }
    } catch (error) {
      setRetainingTestedKey(false);
      setActionError(getErrorMessage(error, '连接测试失败，请检查地址、模型名称和 Key。'));
    } finally {
      const current = form.getFieldsValue();
      form.setFieldsValue(finalizeConnectionTestFields(current, succeeded));
    }
  };

  const showConflictRefresh = () => {
    window.setTimeout(() => {
      modal.confirm({
        title: '配置已在其他页面更新',
        content: '为避免覆盖他人的设置，请先刷新到最新版本后再保存。',
        okText: '立即刷新',
        cancelText: '稍后处理',
        onOk: () => refreshSettings().catch(() => undefined),
      });
    }, 0);
  };

  const handleSave = async () => {
    const request = await validateRequest();
    if (!request) return;

    modal.confirm({
      title: `保存并启用${setting.display_name}？`,
      content:
        '服务端会再次进行真实连接测试；测试通过后，之后启动或重新执行的处理使用新版本，当前正在执行的处理不变。',
      okText: '测试并启用',
      cancelText: '取消',
      onCancel: () => {
        clearApiKey();
        clearLastTest(setting.role);
      },
      onOk: async () => {
        setActionError(null);
        try {
          await saveModel(setting.role, {
            ...request,
            expected_revision: revision,
          });
          message.success(`${setting.display_name}已保存并启用`);
        } catch (error) {
          if (isModelSettingsConflict(error)) {
            showConflictRefresh();
          } else {
            setActionError(getErrorMessage(error, '保存失败，原配置仍然有效。'));
          }
        } finally {
          clearApiKey();
          clearLastTest(setting.role);
        }
      },
    });
  };

  return (
    <Card
      title={
        <Space size={10}>
          <span style={{ color: layoutTokens.primary, fontSize: 18 }}>{ROLE_ICON[setting.role]}</span>
          <span>{setting.display_name}</span>
        </Space>
      }
      extra={
        <Space size={4} wrap>
          <Tag color={setting.source === 'database' ? 'blue' : 'default'}>
            {setting.source === 'database' ? '页面配置' : '环境变量'}
          </Tag>
          <Tag color={keyStatus.color}>{keyStatus.text}</Tag>
        </Space>
      }
      styles={{
        body: { display: 'flex', flexDirection: 'column', minHeight: 430 },
      }}
      style={{ height: '100%', borderColor: layoutTokens.border }}
    >
      {modalContext}
      <Paragraph style={{ color: layoutTokens.textSecondary, minHeight: 44, marginBottom: 16 }}>
        {setting.description}
      </Paragraph>

      <Form<ModelFormValues>
        name={`ai-model-${setting.role}`}
        form={form}
        layout="vertical"
        requiredMark={false}
        disabled={busy}
        onValuesChange={handleValuesChange}
        initialValues={{
          base_url: setting.base_url,
          model_name: setting.model_name,
          api_key: '',
        }}
      >
        <Form.Item
          name="base_url"
          label="API 地址"
          rules={[
            { required: true, message: '请输入 API 地址' },
            { type: 'url', message: '请输入完整的 http:// 或 https:// 地址' },
            {
              validator: (_, value: string | undefined) => {
                const validationError = getBaseUrlValidationError(value ?? '');
                return validationError
                  ? Promise.reject(new Error(validationError))
                  : Promise.resolve();
              },
            },
          ]}
        >
          <Input prefix={<ApiOutlined />} placeholder="例如：http://gateway.internal/v1" />
        </Form.Item>

        <Form.Item
          name="api_key"
          label="API Key"
          dependencies={['base_url']}
          rules={[
            {
              validator: (_, value: string | undefined) => {
                const validationError = getApiKeyValidationError({
                  apiKey: value ?? '',
                  apiKeyStatus: setting.api_key_status,
                  baseUrl: form.getFieldValue('base_url') ?? '',
                  savedBaseUrl: setting.base_url,
                });
                return validationError
                  ? Promise.reject(new Error(validationError))
                  : Promise.resolve();
              },
            },
          ]}
          extra={
            setting.api_key_status === 'unreadable'
              ? '当前 Key 无法解密，测试或保存时必须填写新 Key。'
              : '留空会继续使用当前 Key；更改 API 地址时必须填写新 Key。输入内容仅临时保留在当前卡片。'
          }
        >
          <Input.Password
            autoComplete="new-password"
            placeholder={setting.api_key_status === 'configured' ? '已配置；留空保持不变' : '请输入 API Key'}
          />
        </Form.Item>

        <Form.Item
          name="model_name"
          label="模型名称"
          rules={[{ required: true, whitespace: true, message: '请输入模型名称' }]}
        >
          <Input placeholder="例如：gpt-4.1-mini" />
        </Form.Item>
      </Form>

      <Space size={[8, 6]} wrap style={{ marginBottom: 12 }}>
        <Text type="secondary">最近测试：{formatTestedAt(setting.tested_at)}</Text>
        {setting.role === 'embedding' && (
          <Tag color="purple">固定维度 {setting.vector_dimension ?? 1024}</Tag>
        )}
      </Space>

      {operation.lastTest && (
        <Alert
          showIcon
          type={operation.lastTest.ok ? 'success' : 'warning'}
          message={operation.lastTest.message}
          description={`耗时 ${operation.lastTest.latency_ms} ms${
            operation.lastTest.embedding_dimension
              ? `，向量维度 ${operation.lastTest.embedding_dimension}`
              : ''
          }${retainingTestedKey ? '；新 Key 已临时保留，将用于本次保存' : ''}`}
          style={{ marginBottom: 12 }}
        />
      )}
      {actionError && (
        <Alert showIcon type="error" message={actionError} style={{ marginBottom: 12 }} />
      )}

      <Space wrap style={{ marginTop: 'auto' }}>
        <Button loading={operation.testing} disabled={busy} onClick={handleTest} icon={<EyeOutlined />}>
          测试连接
        </Button>
        <Button
          type="primary"
          loading={operation.saving}
          disabled={busy || !persistenceReady}
          onClick={handleSave}
        >
          保存并启用
        </Button>
      </Space>
    </Card>
  );
}

function AIModelSettingsPage() {
  const {
    settings,
    loading,
    loadError,
    loadErrorKind,
    operations,
    fetchSettings,
    testModel,
    saveModel,
    clearLastTest,
  } = useModelSettingsStore();

  useEffect(() => {
    void fetchSettings().catch(() => undefined);
  }, [fetchSettings]);

  if (loading && !settings) {
    return (
      <PageShell maxWidth={1280}>
        <div style={{ minHeight: '50vh', display: 'grid', placeItems: 'center' }}>
          <Space direction="vertical" align="center" size={12}>
            <Spin size="large" />
            <Text type="secondary">正在加载模型设置…</Text>
          </Space>
        </div>
      </PageShell>
    );
  }

  if (loadError && !settings) {
    return (
      <PageShell maxWidth={1280}>
        <PageHeader title="AI 模型设置" description="管理全平台统一使用的四类 AI 模型。" />
        <Alert
          showIcon
          type="error"
          message={loadErrorKind === 'incomplete' ? '模型配置不完整' : '模型设置加载失败'}
          description={loadError}
          action={
            <Button icon={<ReloadOutlined />} onClick={() => void fetchSettings().catch(() => undefined)}>
              重试
            </Button>
          }
        />
      </PageShell>
    );
  }

  return (
    <PageShell maxWidth={1280}>
      <PageHeader
        eyebrow="全平台设置"
        title="AI 模型设置"
        description="生成、视觉、校验和向量模型相互独立。每张卡片单独测试、保存；当前正在执行的处理保持原模型，之后启动或重新执行的处理使用最新版本。"
        meta={
          settings && (
            <Space size={[8, 6]} wrap>
              <Tag color="blue">当前版本 {settings.revision}</Tag>
              <Tag>{settings.source === 'database' ? '数据库配置' : '环境变量配置'}</Tag>
            </Space>
          )
        }
        actions={
          <Button
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => void fetchSettings().catch(() => undefined)}
          >
            刷新
          </Button>
        }
      />

      <Alert
        showIcon
        type="warning"
        message="当前仅适用于可信内网"
        description="平台目前未启用 HTTPS，API Key 在浏览器到服务端之间通过内网 HTTP 传输。请勿将此页面暴露到公网；服务端保存时会使用总密钥加密。"
        style={{ marginBottom: 16 }}
      />

      {settings && !settings.persistence_ready && (
        <Alert
          showIcon
          type="error"
          message="暂时不能保存配置"
          description="服务端尚未设置模型配置总加密密钥，模型任务仍会在每次开始时读取旧环境变量，但暂时不能从页面保存。请配置总密钥并重启服务后，再从本页保存。"
          style={{ marginBottom: 16 }}
        />
      )}

      {settings && settings.models.length > 0 ? (
        <Row gutter={[16, 16]}>
          {settings.models.map((setting) => (
            <Col key={setting.role} xs={24} xl={12}>
              <ModelSettingCard
                setting={setting}
                revision={settings.revision}
                persistenceReady={settings.persistence_ready}
                operation={operations[setting.role]}
                testModel={testModel}
                saveModel={saveModel}
                clearLastTest={clearLastTest}
                refreshSettings={fetchSettings}
              />
            </Col>
          ))}
        </Row>
      ) : (
        <Alert
          showIcon
          type="error"
          message="未读取到模型配置"
          description="服务返回成功，但没有四类模型数据，请刷新或联系平台维护人员。"
        />
      )}
    </PageShell>
  );
}

export default AIModelSettingsPage;
