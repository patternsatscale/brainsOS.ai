/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APPLIANCE_HOST?: string;
  readonly VITE_BRAINSOS_VERSION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
