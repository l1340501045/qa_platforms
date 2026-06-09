import { Layout, Menu } from 'antd';
import {
  AppstoreOutlined,
  ExportOutlined,
} from '@ant-design/icons';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';

const { Sider, Content, Header } = Layout;

const menuItems = [
  {
    key: '/systems',
    icon: <AppstoreOutlined />,
    label: '系统管理',
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

  // 匹配侧边栏高亮：/systems, /systems/:id/documents, /documents/:id, /batches/:id 都高亮系统管理
  const pathname = location.pathname;
  let selectedKey = '/systems';
  if (pathname.startsWith('/exports')) {
    selectedKey = '/exports';
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
          }}
        >
          <h2 style={{ margin: 0, fontSize: 16 }}>QA 智能测试平台</h2>
        </Header>
        <Content style={{ margin: 24, padding: 24, background: '#fff', borderRadius: 8, overflow: 'auto' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

export default MainLayout;
