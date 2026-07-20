import { useState } from 'react';
import { Button, Drawer, Grid, Layout, Menu } from 'antd';
import {
  ApartmentOutlined,
  AppstoreOutlined,
  AuditOutlined,
  ExportOutlined,
  MenuOutlined,
  SearchOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import NotificationBell from '../components/NotificationBell';
import { layoutTokens } from '../components/layout/tokens';

const { Sider, Content, Header } = Layout;
const { useBreakpoint } = Grid;

const menuItems = [
  {
    key: '/review',
    icon: <AuditOutlined />,
    label: '工作台',
  },
  {
    key: '/systems',
    icon: <AppstoreOutlined />,
    label: '项目/系统',
  },
  {
    key: '/case-library',
    icon: <ApartmentOutlined />,
    label: '用例资产',
  },
  {
    key: '/search',
    icon: <SearchOutlined />,
    label: '全局搜索',
  },
  {
    key: '/exports',
    icon: <ExportOutlined />,
    label: '导出中心',
  },
  {
    key: '/settings/ai-models',
    icon: <SettingOutlined />,
    label: 'AI 模型设置',
  },
];

function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const screens = useBreakpoint();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isDesktop = screens.md !== false;

  // 匹配侧边栏高亮
  const pathname = location.pathname;
  let selectedKey = '/review';
  if (pathname.startsWith('/exports')) {
    selectedKey = '/exports';
  } else if (pathname.startsWith('/settings/ai-models')) {
    selectedKey = '/settings/ai-models';
  } else if (pathname.startsWith('/search')) {
    selectedKey = '/search';
  } else if (pathname.startsWith('/case-library')) {
    selectedKey = '/case-library';
  } else if (pathname.startsWith('/review') || pathname.startsWith('/batches')) {
    selectedKey = '/review';
  } else if (
    pathname.startsWith('/systems') ||
    pathname.startsWith('/documents')
  ) {
    selectedKey = '/systems';
  }

  const currentItem = menuItems.find((item) => item.key === selectedKey);
  const currentDescription =
    selectedKey === '/settings/ai-models'
      ? '配置全平台统一使用的生成、视觉、校验和向量模型'
      : '需求资料、生成批次、审查与用例资产的统一工作台';
  const handleMenuClick = ({ key }: { key: string }) => {
    navigate(key);
    setDrawerOpen(false);
  };

  const renderMenu = () => (
    <Menu
      theme="light"
      mode="inline"
      selectedKeys={[selectedKey]}
      items={menuItems}
      onClick={handleMenuClick}
      style={{ borderInlineEnd: 0, padding: '12px 8px' }}
    />
  );

  const brand = (
    <div
      style={{
        height: layoutTokens.headerHeight,
        display: 'flex',
        alignItems: 'center',
        padding: '0 24px',
        borderBottom: `1px solid ${layoutTokens.border}`,
      }}
    >
      <div
        style={{
          width: 28,
          height: 28,
          borderRadius: 8,
          marginRight: 10,
          color: '#fff',
          background: layoutTokens.primary,
          display: 'grid',
          placeItems: 'center',
          fontSize: 13,
          fontWeight: 700,
          flexShrink: 0,
        }}
      >
        QA
      </div>
      <span style={{ fontWeight: 650, whiteSpace: 'nowrap' }}>QA Platforms</span>
    </div>
  );

  return (
    <Layout style={{ minHeight: '100vh', background: layoutTokens.background }}>
      {isDesktop && (
        <Sider
          width={layoutTokens.sidebarWidth}
          theme="light"
          style={{
            borderRight: `1px solid ${layoutTokens.border}`,
            background: layoutTokens.surface,
          }}
        >
          {brand}
          {renderMenu()}
        </Sider>
      )}
      <Drawer
        title="QA Platforms"
        placement="left"
        width={280}
        open={!isDesktop && drawerOpen}
        onClose={() => setDrawerOpen(false)}
        styles={{
          body: { padding: 0 },
        }}
      >
        {renderMenu()}
      </Drawer>
      <Layout>
        <Header
          style={{
            height: layoutTokens.headerHeight,
            background: layoutTokens.surface,
            padding: isDesktop ? '0 24px' : '0 12px',
            borderBottom: `1px solid ${layoutTokens.border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: isDesktop ? 16 : 8,
          }}
        >
          {!isDesktop && (
            <Button
              type="text"
              aria-label="打开主导航"
              icon={<MenuOutlined />}
              onClick={() => setDrawerOpen(true)}
              style={{ flexShrink: 0 }}
            />
          )}
          <div style={{ minWidth: 0, lineHeight: 1.4, flex: 1 }}>
            <h2
              style={{
                margin: 0,
                fontSize: 16,
                lineHeight: 1.4,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {currentItem?.label || 'QA 智能测试平台'}
            </h2>
            <div
              style={{
                color: layoutTokens.textSecondary,
                fontSize: 12,
                lineHeight: 1.5,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {currentDescription}
            </div>
          </div>
          <div style={{ flexShrink: 0 }}>
            <NotificationBell />
          </div>
        </Header>
        <Content
          style={{
            minWidth: 0,
            padding: isDesktop ? 24 : 12,
            background: layoutTokens.background,
            overflow: 'auto',
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

export default MainLayout;
