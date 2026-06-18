import { Layout, Menu } from 'antd';
import {
  ApartmentOutlined,
  AppstoreOutlined,
  ExportOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import NotificationBell from '../components/NotificationBell';

const { Sider, Content, Header } = Layout;

const menuItems = [
  {
    key: '/systems',
    icon: <AppstoreOutlined />,
    label: '系统管理',
  },
  {
    key: '/case-library',
    icon: <ApartmentOutlined />,
    label: '用例库',
  },
  {
    key: '/search',
    icon: <SearchOutlined />,
    label: '用例搜索',
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
  let selectedKey = '/systems';
  if (pathname.startsWith('/exports')) {
    selectedKey = '/exports';
  } else if (pathname.startsWith('/search')) {
    selectedKey = '/search';
  } else if (pathname.startsWith('/case-library')) {
    selectedKey = '/case-library';
  } else if (
    pathname.startsWith('/systems') ||
    pathname.startsWith('/documents') ||
    pathname.startsWith('/batches')
  ) {
    selectedKey = '/systems';
  }

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider width={220} theme="dark">
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontSize: 18,
            fontWeight: 'bold',
          }}
        >
          QA Platforms
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            borderBottom: '1px solid #f0f0f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <h2 style={{ margin: 0, fontSize: 16 }}>QA 智能测试平台</h2>
          <NotificationBell />
        </Header>
        <Content style={{ margin: 24, padding: 24, background: '#fff', borderRadius: 8, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

export default MainLayout;
