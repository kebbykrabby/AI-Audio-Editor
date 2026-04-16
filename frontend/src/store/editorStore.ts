import { create } from "zustand";
import type { Asset, Selection } from "./types";

interface ChannelEditState {
  leftAsset: Asset;
  rightAsset: Asset;
  activeChannel: "left" | "right";
  originalAssetId: string;
}

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
  channelEdit: ChannelEditState | null;

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
  enterChannelEdit: (originalAssetId: string, left: Asset, right: Asset) => void;
  updateChannelAsset: (channel: "left" | "right", asset: Asset) => void;
  setActiveChannel: (ch: "left" | "right") => void;
  exitChannelEdit: () => void;
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
  channelEdit: null,

  currentAsset: () => {
    const { channelEdit, assetHistory, currentIndex } = get();
    if (channelEdit) {
      return channelEdit.activeChannel === "left"
        ? channelEdit.leftAsset
        : channelEdit.rightAsset;
    }
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

  enterChannelEdit: (originalAssetId, left, right) => {
    set({
      channelEdit: { leftAsset: left, rightAsset: right, activeChannel: "left", originalAssetId },
      selection: null,
      warning: null,
    });
  },

  updateChannelAsset: (channel, asset) => {
    const ce = get().channelEdit;
    if (!ce) return;
    set({
      channelEdit: {
        ...ce,
        leftAsset: channel === "left" ? asset : ce.leftAsset,
        rightAsset: channel === "right" ? asset : ce.rightAsset,
      },
    });
  },

  setActiveChannel: (ch) => {
    const ce = get().channelEdit;
    if (!ce) return;
    set({ channelEdit: { ...ce, activeChannel: ch }, selection: null });
  },

  exitChannelEdit: () => set({ channelEdit: null, selection: null }),

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
      channelEdit: null,
    });
  },
}));
