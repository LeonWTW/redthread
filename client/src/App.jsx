import { BrowserRouter, Outlet, Route, Routes } from 'react-router-dom'
import Nav from './components/Nav.jsx'
import Capture from './pages/Capture.jsx'
import Inbox from './pages/Inbox.jsx'
import Login from './pages/Login.jsx'
import Placeholder from './pages/Placeholder.jsx'
import PostView from './pages/PostView.jsx'
import './app.css'

// The five screens: Inbox, Triage, Library, Report Editor, Export Preview —
// and only those five. Unbuilt ones render a Placeholder until their
// milestone. Nav appears on every page except Login.
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
          <Route path="/triage" element={<Placeholder title="Triage" />} />
          <Route path="/library" element={<Placeholder title="Library" />} />
          <Route path="/reports" element={<Placeholder title="Report Editor" />} />
          <Route path="/export" element={<Placeholder title="Export Preview" />} />
          <Route path="/posts/:id" element={<PostView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
