import Constants from "expo-constants";
import { Platform } from "react-native";

type ExtraConfig = {
  apiBase?: string;
};

function resolveApiBase(): string {
  const envApiBase = process.env.EXPO_PUBLIC_API_BASE;
  if (envApiBase && envApiBase.trim().length > 0) {
    return envApiBase.trim();
  }

  const extra = (Constants.expoConfig?.extra ?? {}) as ExtraConfig;
  if (extra.apiBase && extra.apiBase.trim().length > 0) {
    return extra.apiBase.trim();
  }

  // Sensible defaults for local development when no explicit base URL is set.
  if (Platform.OS === "android") {
    return "http://10.0.2.2:8000";
  }
  return "http://127.0.0.1:8000";
}

export const API_BASE = resolveApiBase();

export const UPLOAD_TIMEOUT_MS = 120_000;
