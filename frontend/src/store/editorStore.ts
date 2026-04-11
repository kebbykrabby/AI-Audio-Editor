import { create } from "zustand";
import type { Asset, Selection } from "./types";

interface EditorState {
  assetHistory: Asset[];
  currentIndex: number;
  isPlaying: boolean;
  currentTimeSec: number;
  selection: Selection | null;
  isUploading: boolean;
  isProcessing: boolean;
  error: string | null;
  warning: string | null;

  currentAsset: () => Asset | null;
  canUndo: () => boolean;
  canRedo: () => boolean;

  setAssetReady: (asset: Asset) => void;
  pushAsset: (asset: Asset, durationChanged: boolean) => void;
  undo: () => void;
  redo: () => void;
  setSelection: (sel: Selection | null) => void;
  setPlaying: (playing: boolean) => void;
  setCurrentTime: (sec: number) => void;
  setUploading: (v: boolean) => void;
  setProcessing: (v: boolean) => void;
  setError: (msg: string | null) => void;
  setWarning: (msg: string | null) => void;
  reset: () => void;
}

const MAX_HISTORY = 100;

export const useEditorStore = create<EditorState>((set, get) => ({
  assetHistory: [],
  currentIndex: -1,
  isPlaying: false,
  currentTimeSec: 0,
  selection: null,
  isUploading: false,
  isProcessing: false,
  error: null,
  warning: null,

  currentAsset: () => {
    const { assetHistory, currentIndex } = get();
    return currentIndex >= 0 ? assetHistory[currentIndex] : null;
  },

  canUndo: () => get().currentIndex > 0,
  canRedo: () => get().currentIndex < get().assetHistory.length - 1,

  setAssetReady: (asset) => {
    set({ assetHistory: [asset], currentIndex: 0, error: null, warning: null });
  },

  pushAsset: (asset, durationChanged) => {
    const { assetHistory, currentIndex } = get();
    let newHistory = assetHistory.slice(0, currentIndex + 1);
    newHistory.push(asset);
    let newIndex = newHistory.length - 1;
    // Cap history to prevent unbounded memory growth
    if (newHistory.length > MAX_HISTORY) {
      const overflow = newHistory.length - MAX_HISTORY;
      newHistory = newHistory.slice(overflow);
      newIndex -= overflow;
    }
    set({
      assetHistory: newHistory,
      currentIndex: newIndex,
      selection: durationChanged ? null : get().selection,
      warning: null,
    });
  },

  undo: () => {
    const { currentIndex, assetHistory } = get();
    if (currentIndex > 0) {
      const newIndex = currentIndex - 1;
      set({ currentIndex: newIndex, selection: null, warning: null });
      }
  },

  redo: () => {
    const { currentIndex, assetHistory } = get();
    if (currentIndex < assetHistory.length - 1) {
      const newIndex = currentIndex + 1;
      set({ currentIndex: newIndex, selection: null, warning: null });
      }
  },

  setSelection: (sel) => set({ selection: sel }),
  setPlaying: (playing) => set({ isPlaying: playing }),
  setCurrentTime: (sec) => set({ currentTimeSec: sec }),
  setUploading: (v) => set({ isUploading: v }),
  setProcessing: (v) => set({ isProcessing: v }),
  setError: (msg) => set({ error: msg }),
  setWarning: (msg) => set({ warning: msg }),

  reset: () => {
    set({
      assetHistory: [],
      currentIndex: -1,
      isPlaying: false,
      currentTimeSec: 0,
      selection: null,
      isUploading: false,
      isProcessing: false,
      error: null,
      warning: null,
    });
  },
}));
