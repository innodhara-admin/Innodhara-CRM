/**
 * Hash routing — 07_BUILD_PLAN.md A8, from finding P10.
 *
 * `createHashRouter`, not `createBrowserRouter`. The backend serves this bundle
 * with `StaticFiles(directory=…, html=True)`, and that does **not** fall back to
 * `index.html` for unknown sub-paths — it serves `index.html` only for a
 * directory URL, then looks for `404.html`, then 404s. Proved in Task 11:
 *
 *     GET /dashboard/            200
 *     GET /dashboard/checklist   404
 *
 * So a path-routed console would work perfectly while clicking through and
 * break on every refresh, bookmark and shared link. Every URL here is
 * `/dashboard/#/…`, which the server only ever sees as `/dashboard/`.
 *
 * **Do not switch this to a browser router** without a backend fallback route,
 * which the change list — closed at ten — does not have.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { createHashRouter, Navigate, RouterProvider } from "react-router-dom";

import { queryClient } from "../api/queryClient";
import { Checklist } from "../screens/Checklist";
import { CreateOrg } from "../screens/CreateOrg";
import { DocxEditor } from "../screens/docx/DocxEditor";
import { Bundle } from "../screens/Bundle";
import { GoLive } from "../screens/GoLive";
import { ImportScreen } from "../screens/ImportScreen";
import { Reset } from "../screens/Reset";
import { SignIn } from "../screens/SignIn";
import { Styleguide } from "../screens/Styleguide";
import { session } from "../session/store";

/** Land wherever the current session can actually go. */
function Landing() {
  const { superToken, org } = session.get();
  if (org) return <Navigate to="/checklist" replace />;
  if (superToken) return <Navigate to="/orgs" replace />;
  return <Navigate to="/sign-in" replace />;
}

const router = createHashRouter([
  { path: "/", element: <Landing /> },
  { path: "/sign-in", element: <SignIn /> },
  { path: "/orgs", element: <CreateOrg /> },
  { path: "/checklist", element: <Checklist /> },
  // The one screen reached from an item rather than from the rail. Item
  // screens render inside the checklist; this one is a document and needs
  // the whole pane, so it is a route of its own and carries the doc id in
  // the URL - which also makes it a link an administrator can come back to.
  { path: "/item/6/doc/:docId", element: <DocxEditor /> },
  { path: "/import", element: <ImportScreen /> },
  { path: "/go-live", element: <GoLive /> },
  { path: "/reset", element: <Reset /> },
  { path: "/bundle", element: <Bundle /> },
  { path: "/styleguide", element: <Styleguide /> },
  { path: "*", element: <Landing /> },
]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
