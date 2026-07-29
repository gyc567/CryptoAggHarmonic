import "@testing-library/jest-dom";
import { vi } from "vitest";

// Mock matchMedia for theme hook tests
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

Object.defineProperty(window, "localStorage", {
  value: localStorageMock,
});

// Mock Supabase env vars (must satisfy isSupabaseConfigured: real-looking URL + key length >= 20)
process.env.NEXT_PUBLIC_SUPABASE_URL = "https://e2e-test.supabase.co";
process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "e2e-test-anon-key-padded";
