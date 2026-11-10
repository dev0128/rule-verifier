import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import './styles.css'
import Overview from './pages/Overview'
import Finding from './pages/Finding'
import Diagnoses from './pages/Diagnoses'
import Run from './pages/Run'
import Variants from './pages/Variants'
import Playground from './pages/Playground'
import Help from './pages/Help'
import ApiRef from './pages/ApiRef'

function Layout() {
  return (
    <div className="layout">
      <nav className="nav">
        <div className="brand">
          D-CLO 룰 검증
          <small>AWS 기본 룰 · 엔진 비교</small>
        </div>
        <NavLink to="/" end>
          결함 검증 현황
        </NavLink>
        <NavLink to="/diagnoses">실데이터 실행</NavLink>
        <NavLink to="/playground">입력 실험</NavLink>
        <NavLink to="/apiref">AWS API 참고</NavLink>
        <NavLink to="/variants">엔진 변형</NavLink>
        <NavLink to="/help">용어 도움말</NavLink>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/findings/:id" element={<Finding />} />
          <Route path="/diagnoses" element={<Diagnoses />} />
          <Route path="/runs/:id" element={<Run />} />
          <Route path="/variants" element={<Variants />} />
          <Route path="/playground" element={<Playground />} />
          <Route path="/apiref" element={<ApiRef />} />
          <Route path="/help" element={<Help />} />
        </Routes>
      </main>
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  </StrictMode>,
)
