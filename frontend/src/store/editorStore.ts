import { create } from "zustand";
import type { Asset, Selection } from "./types";

const STORAGE_KEY = "audioEditor.currentAssetId";
const PENDING_OP_KEY = "audioEditor.pendingOperation";

function persistCurrentAssetId(id: string | null): void {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // localStorage unavailable (private mode, quota) — fail silently
  }
}

export function readPersistedAssetId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function clearPersistedAssetId(): void {
  persistCurrentAssetId(null);
}

export interface PendingOperation {
  operationId: string;
  type: string;
  inputAssetId: string;
  startedAt: number;
}

function persistPendingOp(op: PendingOperation | null): void {
  try {
    if (op) localStorage.setItem(PENDING_OP_KEY, JSON.stringify(op));
    else localStorage.removeItem(PENDING_OP_KEY);
  } catch {
    // fail silently
  }
}

export function readPersistedPendingOp(): PendingOperation | null {
  try {
    const raw = localStorage.getItem(PENDING_OP_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PendingOperation;
    if (!parsed.operationId || !parsed.inputAssetId || !parsed.type) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function clearPersistedPendingOp(): void {
  persistPendingOp(null);
}

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
  pendingOperation: PendingOperation | null;
  error: string | null;
  warning: string | null;
  channelEdit: ChannelEditState | null;

  currentAsset: () => Asset | null;
  canUndo: () => boolean;
  canRedo: () => boolean;

  setAssetReady: (asset: Asset) => void;
  pushAsset: (asset: Asset, durationChanged: boolean) => void;
  refreshAssetUrls: (
    assetId: string,
    audioUrl: string | null,
    waveformUrl: string | null,
  ) => void;
  undo: () => void;
  redo: () => void;
  setSelection: (sel: Selection | null) => void;
  setPlaying: (playing: boolean) => void;
  setCurrentTime: (sec: number) => void;
  setUploading: (v: boolean) => void;
  setProcessing: (v: boolean) => void;
  setPendingOperation: (op: PendingOperation | null) => void;
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
  pendingOperation: null,
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
    persistCurrentAssetId(asset.assetId);
  },

  pushAsset: (asset, durationChanged) => {
    const { assetHistory, currentIndex } = get();
    let newHistory = assetHistory.slice(0, currentIndex + 1);
    newHistory.push(asset);
    let newIndex = newHistory.length - 1;
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
    persistCurrentAssetId(asset.assetId);
  },

  refreshAssetUrls: (assetId, audioUrl, waveformUrl) => {
    const { assetHistory, channelEdit } = get();
    const patch = (a: Asset): Asset =>
      a.assetId === assetId ? { ...a, audioUrl, waveformUrl } : a;

    const nextHistory = assetHistory.map(patch);
    const nextChannelEdit = channelEdit
      ? {
          ...channelEdit,
          leftAsset: patch(channelEdit.leftAsset),
          rightAsset: patch(channelEdit.rightAsset),
        }
      : null;
    set({ assetHistory: nextHistory, channelEdit: nextChannelEdit });
  },

  undo: () => {
    const { currentIndex, assetHistory } = get();
    if (currentIndex > 0) {
      const newIndex = currentIndex - 1;
      set({ currentIndex: newIndex, selection: null, warning: null });
      persistCurrentAssetId(assetHistory[newIndex].assetId);
    }
  },

  redo: () => {
    const { currentIndex, assetHistory } = get();
    if (currentIndex < assetHistory.length - 1) {
      const newIndex = currentIndex + 1;
      set({ currentIndex: newIndex, selection: null, warning: null });
      persistCurrentAssetId(assetHistory[newIndex].assetId);
    }
  },

  setSelection: (sel) => set({ selection: sel }),
  setPlaying: (playing) => set({ isPlaying: playing }),
  setCurrentTime: (sec) => set({ currentTimeSec: sec }),
  setUploading: (v) => set({ isUploading: v }),
  setProcessing: (v) => set({ isProcessing: v }),

  setPendingOperation: (op) => {
    persistPendingOp(op);
    set({ pendingOperation: op, isProcessing: op !== null });
  },

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
      pendingOperation: null,
      error: null,
      warning: null,
      channelEdit: null,
    });
    clearPersistedAssetId();
    clearPersistedPendingOp();
  },
}));
