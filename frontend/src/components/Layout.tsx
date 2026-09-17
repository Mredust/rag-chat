import {
  BarChart3,
  BookOpen,
  Box,
  ChevronDown,
  ChevronRight,
  Cpu,
  Database,
  LogOut,
  MessageSquare,
  Settings,
  SlidersHorizontal,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive ? 'bg-indigo-50 text-indigo-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
  }`

export default function Layout() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const location = useLocation()

  const [trainOpen, setTrainOpen] = useState(location.pathname.startsWith('/ml'))

  useEffect(() => {
    if (location.pathname.startsWith('/ml')) setTrainOpen(true)
  }, [location.pathname])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const isMlActive = location.pathname.startsWith('/ml')

  return (
    <div className="flex h-screen">
      {/* 左侧菜单栏 */}
      <aside className="flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex h-16 items-center gap-2.5 border-b border-slate-100 px-4">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-white">
            <BookOpen size={20} />
          </span>
          <span className="text-base font-semibold text-slate-900">RAG Chat</span>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          <NavLink to="/chat" className={navLinkClass}>
            <MessageSquare size={18} />
            智能问答
          </NavLink>
          <NavLink to="/" end className={navLinkClass}>
            <BookOpen size={18} />
            知识库
          </NavLink>

          {/* 模型训练（一级菜单，可展开为二级菜单） */}
          <button
            type="button"
            onClick={() => setTrainOpen((v) => !v)}
            className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isMlActive ? 'text-indigo-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
              }`}
          >
            <Cpu size={18} />
            <span className="flex-1 text-left">模型训练</span>
            {trainOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>

          {trainOpen && (
            <div className="ml-3 space-y-1 border-l border-slate-200 pl-2">
              <NavLink to="/ml/datasets" className={navLinkClass}>
                <Database size={16} />
                数据管理
              </NavLink>
              <NavLink to="/ml/models" className={navLinkClass}>
                <Box size={16} />
                我的模型
              </NavLink>
              <NavLink to="/ml/tune" className={navLinkClass}>
                <SlidersHorizontal size={16} />
                模型调优
              </NavLink>
              <NavLink to="/ml/eval" className={navLinkClass}>
                <BarChart3 size={16} />
                模型评测
              </NavLink>
            </div>
          )}

        </nav>

        {/* 底部：用户信息、系统设置、退出登录 */}
        <div className="space-y-1 border-t border-slate-200 p-3">
          <div className="flex items-center gap-2 rounded-lg px-3 py-2">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-sm font-semibold text-indigo-700">
              {(user?.username ?? '用').slice(0, 1).toUpperCase()}
            </span>
            <span className="truncate text-sm font-medium text-slate-700">{user ? user.username : ''}</span>
          </div>
          <NavLink to="/settings" className={navLinkClass}>
            <Settings size={18} />
            系统设置
          </NavLink>
          <button
            type="button"
            onClick={handleLogout}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
          >
            <LogOut size={18} />
            退出登录
          </button>
        </div>
      </aside>

      {/* 右侧内容区 */}
      <main className="flex-1 overflow-y-auto px-6 py-6">
        <Outlet />
      </main>
    </div>
  )
}