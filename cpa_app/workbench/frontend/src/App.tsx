import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Box, CircularProgress } from "@mui/material";
import { useMe } from "./hooks";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Cases from "./pages/Cases";
import Queue from "./pages/Queue";
import NewCase from "./pages/NewCase";
import CasePage from "./pages/CasePage";

export default function App() {
  const me = useMe();
  const loc = useLocation();
  if (me.isLoading) return <Box sx={{ display: "grid", placeItems: "center", height: "100vh" }}><CircularProgress /></Box>;
  if (!me.data) {
    return (
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />} />
      </Routes>
    );
  }
  return (
    <Layout me={me.data}>
      <Routes>
        <Route path="/" element={<Cases />} />
        <Route path="/queue" element={<Queue />} />
        <Route path="/cases/new" element={<NewCase />} />
        <Route path="/cases/:sid" element={<CasePage />} />
        <Route path="/cases/:sid/:tab" element={<CasePage />} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
