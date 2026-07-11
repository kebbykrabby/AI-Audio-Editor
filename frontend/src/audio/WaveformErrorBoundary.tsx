import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  onReset: () => void;
}

interface State {
  hasError: boolean;
}

export default class WaveformErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="w-full rounded-xl border border-destructive/30 bg-destructive/5 p-8 text-center">
          <p className="text-destructive text-sm mb-3">
            Waveform display crashed. The audio file may be corrupt or in an unsupported format.
          </p>
          <button
            onClick={() => {
              this.setState({ hasError: false });
              this.props.onReset();
            }}
            className="inline-flex items-center px-4 py-2 rounded-md bg-secondary text-secondary-foreground text-sm hover:bg-muted transition-colors"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
