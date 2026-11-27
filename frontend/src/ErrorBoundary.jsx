import React from "react";

export default class ErrorBoundary extends React.Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <section role="alert" className="panel notice error">
          <h2>The workspace could not be displayed</h2>
          <p>
            If an upload was in progress, check its status after retrying or
            reloading the workspace.
          </p>
          <div className="actions">
            <button onClick={() => this.setState({ failed: false })}>
              Try again
            </button>
            <button
              className="secondary"
              onClick={() => window.location.reload()}
            >
              Reload page
            </button>
          </div>
        </section>
      );
    }
    return this.props.children;
  }
}
