// Browser-test entry only. It is not imported by the production portal.
import React from "react";
import { createRoot } from "react-dom/client";
import ErrorBoundary from "../src/ErrorBoundary";
window.boundaryShouldThrow = true;
function Probe() {
  if (window.boundaryShouldThrow) throw new Error("Synthetic render failure");
  return <p>Workspace recovered</p>;
}
createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <Probe />
  </ErrorBoundary>,
);
