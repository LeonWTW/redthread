import { BrowserRouter, Outlet, Route, Routes } from 'react-router-dom'
import Nav from './components/Nav.jsx'
import Capture from './pages/Capture.jsx'
import ExportPreview from './pages/ExportPreview.jsx'
import Inbox from './pages/Inbox.jsx'
import Library from './pages/Library.jsx'
import Login from './pages/Login.jsx'
import PostView from './pages/PostView.jsx'
import ReportEditor from './pages/ReportEditor.jsx'
import Reports from './pages/Reports.jsx'
import Triage from './pages/Triage.jsx'
import './app.css'

// The five screens: Inbox, Triage, Library, Report Editor, Export Preview —
// and only those five. Nav appears on every page except Login.
function Shell() {
  return (
    <>
      <Nav />
      <Outlet />
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<Shell />}>
          <Route path="/" element={<Capture />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/triage" element={<Triage />} />
          <Route path="/library" element={<Library />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/reports/:id" element={<ReportEditor />} />
          <Route path="/export" element={<ExportPreview />} />
          <Route path="/posts/:id" element={<PostView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
