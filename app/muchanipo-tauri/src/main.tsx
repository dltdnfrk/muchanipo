import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

interface BootErrorBoundaryState {
  error: Error | null;
}

class BootErrorBoundary extends React.Component<React.PropsWithChildren, BootErrorBoundaryState> {
  state: BootErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BootErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    document.documentElement.dataset.muchanipoBoot = "react-error";
    console.error("Muchanipo React boot error", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="app-workspace flex min-h-screen items-center justify-center p-6">
        <section className="w-full max-w-2xl rounded-lg border border-red-500/30 bg-red-500/10 p-5 text-red-100">
          <p className="font-mono text-[11px] uppercase tracking-wider text-red-200">
            Muchanipo React boot error
          </p>
          <h1 className="mt-2 text-xl font-semibold text-white">
            Frontend shell failed before the app could render.
          </h1>
          <pre className="mt-4 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border border-red-500/20 bg-black/30 p-3 text-xs leading-relaxed">
            {this.state.error.stack || this.state.error.message}
          </pre>
        </section>
      </main>
    );
  }
}

const root = document.getElementById("root");

if (!root) {
  document.documentElement.dataset.muchanipoBoot = "missing-root";
  document.body.innerHTML =
    '<pre style="white-space:pre-wrap;margin:0;padding:24px;color:#fecaca;background:#0d0e0e;min-height:100vh;box-sizing:border-box;font:13px ui-monospace,SFMono-Regular,Menlo,monospace">Muchanipo frontend boot error:\\n#root element is missing</pre>';
} else {
  document.documentElement.dataset.muchanipoBoot = "react-starting";
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <BootErrorBoundary>
        <App />
      </BootErrorBoundary>
    </React.StrictMode>,
  );
  window.requestAnimationFrame(() => {
    if (document.documentElement.dataset.muchanipoBoot === "react-starting") {
      document.documentElement.dataset.muchanipoBoot = "react-mounted";
    }
  });
}
