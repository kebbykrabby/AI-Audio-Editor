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
        <div className="w-full rounded-lg bg-slate-900 border border-red-800 p-8 text-center">
          <p className="text-red-400 text-sm mb-3">
            Waveform display crashed. The audio file may be corrupt or in an unsupported format.
          </p>
          <button
            onClick={() => {
              this.setState({ hasError: false });
              this.props.onReset();
            }}
            className="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded text-sm text-slate-200"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
