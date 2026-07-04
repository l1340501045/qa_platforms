import { Layout, Menu } from 'antd';
import {
  ApartmentOutlined,
  AppstoreOutlined,
  AuditOutlined,
  ExportOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import NotificationBell from '../components/NotificationBell';
import { layoutTokens } from '../components/layout/tokens';

const { Sider, Content, Header } = Layout;

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
];

function MainLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  // 匹配侧边栏高亮
  const pathname = location.pathname;
  let selectedKey = '/review';
  if (pathname.startsWith('/exports')) {
    selectedKey = '/exports';
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

  return (
    <Layout style={{ minHeight: '100vh', background: layoutTokens.background }}>
      <Sider
        width={layoutTokens.sidebarWidth}
        theme="light"
        style={{
          borderRight: `1px solid ${layoutTokens.border}`,
          background: layoutTokens.surface,
        }}
      >
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
            }}
          >
            QA
          </div>
          QA Platforms
        </div>
        <Menu
          theme="light"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderInlineEnd: 0, padding: '12px 8px' }}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            height: layoutTokens.headerHeight,
            background: layoutTokens.surface,
            padding: '0 24px',
            borderBottom: `1px solid ${layoutTokens.border}`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ minWidth: 0, lineHeight: 1.4 }}>
            <h2 style={{ margin: 0, fontSize: 16, lineHeight: 1.4 }}>
              {currentItem?.label || 'QA 智能测试平台'}
            </h2>
            <div style={{ color: layoutTokens.textSecondary, fontSize: 12, lineHeight: 1.5 }}>
              需求资料、生成批次、审查与用例资产的统一工作台
            </div>
          </div>
          <NotificationBell />
        </Header>
        <Content
          style={{
            minWidth: 0,
            padding: 24,
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
