import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-left">
          <NavLink to="/" className="logo">
            <span className="logo-icon">🎬</span>
            <span className="logo-text">Pere</span>
          </NavLink>
          <nav className="nav-links">
            <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              任务列表
            </NavLink>
            <NavLink to="/create" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              创建任务
            </NavLink>
            <NavLink to="/files" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              文件管理
            </NavLink>
          </nav>
        </div>
        <div className="header-right">
          <span className="user-info">
            {user?.username || '未登录'}
          </span>
          <button className="btn btn-ghost" onClick={handleLogout}>
            退出
          </button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
